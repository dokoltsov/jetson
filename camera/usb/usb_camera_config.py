"""Arducam day/night camera configuration GUI.

Live preview with interactive controls — move a slider, change takes effect
immediately on the camera. Click Save to write current settings to JSON.

Usage:
    python3 usb_camera_config.py
    python3 usb_camera_config.py --config usb_camera.json   # load existing config
    python3 usb_camera_config.py --camera-index 1
"""

import argparse
import json
import queue
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageTk
import tkinter as tk
from tkinter import messagebox, ttk


_BY_ID = "/dev/v4l/by-id/usb-Arducam_Technology_Co.__Ltd._USB_Camera_SN0001-video-index0"

def _resolve_index(fallback: int = 2) -> int:
    import os
    try:
        target = os.path.realpath(_BY_ID)
        return int(target.replace("/dev/video", ""))
    except Exception:
        return fallback
PREVIEW_W = 640
PREVIEW_H = 360
CONFIG_FILE = Path(__file__).parent / "usb_camera.json"


# ── Control definitions ───────────────────────────────────────────────────────

@dataclass
class CameraState:
    mode: str = "auto"
    # Image controls
    brightness: int = 0
    contrast: int = 32
    saturation: int = 64
    hue: int = 0
    gamma: int = 100
    gain: int = 0
    sharpness: int = 10
    backlight_compensation: int = 80
    # Exposure
    auto_exposure: bool = True          # True = aperture priority
    exposure_time: int = 157
    exposure_dynamic_framerate: bool = True
    # White balance
    white_balance_auto: bool = True
    white_balance_temperature: int = 4600
    # Anti-flicker
    power_line_frequency: int = 1       # 0=off 1=50Hz 2=60Hz


MODE_PRESETS = {
    "day": CameraState(
        mode="day",
        auto_exposure=True,
        exposure_dynamic_framerate=True,
        white_balance_auto=True,
        saturation=64,
        gain=0,
        backlight_compensation=80,
    ),
    "night": CameraState(
        mode="night",
        auto_exposure=False,
        exposure_time=5000,
        exposure_dynamic_framerate=False,
        white_balance_auto=False,
        saturation=0,
        gain=100,
        backlight_compensation=0,
    ),
}

CTRL_RANGES = {
    "brightness":               (-64,  64,   1),
    "contrast":                 (  0,  64,   1),
    "saturation":               (  0, 128,   1),
    "hue":                      (-40,  40,   1),
    "gamma":                    ( 72, 500,   1),
    "gain":                     (  0, 100,   1),
    "sharpness":                (  0,  14,   1),
    "backlight_compensation":   (  0, 160,   1),
    "exposure_time":            (  1,5000,   1),
    "white_balance_temperature":(2800,6500, 100),
}

V4L2_CTRL_MAP = {
    "brightness":               "brightness",
    "contrast":                 "contrast",
    "saturation":               "saturation",
    "hue":                      "hue",
    "gamma":                    "gamma",
    "gain":                     "gain",
    "sharpness":                "sharpness",
    "backlight_compensation":   "backlight_compensation",
    "exposure_time":            "exposure_time_absolute",
    "white_balance_temperature":"white_balance_temperature",
    "auto_exposure":            "auto_exposure",           # special: maps bool → 1/3
    "white_balance_auto":       "white_balance_automatic",
    "exposure_dynamic_framerate":"exposure_dynamic_framerate",
}


# ── Camera capture thread ─────────────────────────────────────────────────────

class CaptureThread(threading.Thread):
    def __init__(self, device: str, camera_index: int, frame_queue: queue.Queue):
        super().__init__(daemon=True)
        self.device = device
        self.camera_index = camera_index
        self.frame_queue = frame_queue
        self._stop = threading.Event()

    def run(self):
        self._cap = None
        # Retry open — device may be briefly busy after prior run
        for attempt in range(5):
            cap = cv2.VideoCapture(self.camera_index, cv2.CAP_V4L2)
            if cap.isOpened():
                self._cap = cap
                break
            cap.release()
            print(f"[capture] open attempt {attempt+1}/5 failed, retrying...", flush=True)
            time.sleep(1.0)
        else:
            print("[capture] could not open camera", flush=True)
            return

        self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self._cap.set(cv2.CAP_PROP_FPS, 30)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 4)
        time.sleep(1.0)  # warmup

        while not self._stop.is_set():
            cap = self._cap
            if cap is None:
                break
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.05)
                continue
            frame = cv2.resize(frame, (PREVIEW_W, PREVIEW_H))
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            try:
                self.frame_queue.get_nowait()
            except queue.Empty:
                pass
            self.frame_queue.put(frame)

        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def stop(self):
        self._stop.set()

    def release(self):
        """Release the camera immediately from the main thread.

        cap.read() blocks, so we can't wait for the capture loop to exit.
        Calling cap.release() from outside unblocks the pending read and
        causes it to return False, which lets the loop check _stop and exit.
        """
        if self._cap is not None:
            self._cap.release()
            self._cap = None


# ── v4l2 helpers ──────────────────────────────────────────────────────────────

def v4l2_set(device: str, ctrl: str, value: int):
    subprocess.run(
        ["v4l2-ctl", f"--device={device}", f"--set-ctrl={ctrl}={value}"],
        capture_output=True,
    )


def apply_ctrl(device: str, field: str, value):
    """Translate a CameraState field name + value to a v4l2-ctl call."""
    if field == "auto_exposure":
        v4l2_set(device, "auto_exposure", 3 if value else 1)
    elif field in V4L2_CTRL_MAP:
        v4l2_set(device, V4L2_CTRL_MAP[field], int(value))


# ── GUI ───────────────────────────────────────────────────────────────────────

class ConfigGUI:
    def __init__(self, root: tk.Tk, device: str, camera_index: int, initial_state: CameraState, config_path: Path):
        self.root = root
        self.device = device
        self.state = initial_state
        self.config_path = config_path

        self.root.title("Arducam Config")
        self.root.resizable(False, False)

        self.frame_queue: queue.Queue = queue.Queue(maxsize=1)
        self._capture = CaptureThread(device, camera_index, self.frame_queue)

        self._build_ui()
        self._capture.start()
        self._schedule_preview()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Left: live preview ─────────────────────────────────────────────
        left = tk.Frame(self.root, bg="black")
        left.grid(row=0, column=0, padx=8, pady=8, sticky="n")

        self._preview_label = tk.Label(left, bg="black")
        self._preview_label.pack()

        tk.Label(left, text=f"{PREVIEW_W}×{PREVIEW_H} preview  |  {self.device}",
                 bg="black", fg="#888", font=("monospace", 9)).pack(pady=(2, 0))

        # ── Right: controls ────────────────────────────────────────────────
        right = ttk.Frame(self.root, padding=8)
        right.grid(row=0, column=1, padx=(0, 8), pady=8, sticky="n")

        # Mode buttons
        mode_frame = ttk.LabelFrame(right, text="Mode", padding=6)
        mode_frame.pack(fill="x", pady=(0, 8))

        self._mode_var = tk.StringVar(value=self.state.mode)
        for m in ("auto", "day", "night"):
            ttk.Radiobutton(
                mode_frame, text=m.capitalize(), value=m,
                variable=self._mode_var, command=self._on_mode_change,
            ).pack(side="left", padx=8)

        # Sliders
        sliders_frame = ttk.LabelFrame(right, text="Image Controls", padding=6)
        sliders_frame.pack(fill="x", pady=(0, 8))
        self._sliders: dict[str, tk.IntVar] = {}
        self._slider_widgets: dict[str, ttk.Scale] = {}

        slider_defs = [
            ("brightness",             "Brightness"),
            ("contrast",               "Contrast"),
            ("saturation",             "Saturation"),
            ("hue",                    "Hue"),
            ("gamma",                  "Gamma"),
            ("gain",                   "Gain"),
            ("sharpness",              "Sharpness"),
            ("backlight_compensation", "Backlight Comp"),
        ]
        for field, label in slider_defs:
            self._add_slider(sliders_frame, field, label)

        # Exposure section
        exp_frame = ttk.LabelFrame(right, text="Exposure", padding=6)
        exp_frame.pack(fill="x", pady=(0, 8))

        self._auto_exp_var = tk.BooleanVar(value=self.state.auto_exposure)
        ttk.Checkbutton(
            exp_frame, text="Auto Exposure",
            variable=self._auto_exp_var,
            command=lambda: self._on_bool_change("auto_exposure", self._auto_exp_var),
        ).pack(anchor="w")

        self._add_slider(exp_frame, "exposure_time", "Exposure Time")

        self._dyn_fps_var = tk.BooleanVar(value=self.state.exposure_dynamic_framerate)
        ttk.Checkbutton(
            exp_frame, text="Dynamic Framerate",
            variable=self._dyn_fps_var,
            command=lambda: self._on_bool_change("exposure_dynamic_framerate", self._dyn_fps_var),
        ).pack(anchor="w")

        # White balance section
        wb_frame = ttk.LabelFrame(right, text="White Balance", padding=6)
        wb_frame.pack(fill="x", pady=(0, 8))

        self._wb_auto_var = tk.BooleanVar(value=self.state.white_balance_auto)
        ttk.Checkbutton(
            wb_frame, text="Auto White Balance",
            variable=self._wb_auto_var,
            command=lambda: self._on_bool_change("white_balance_auto", self._wb_auto_var),
        ).pack(anchor="w")

        self._add_slider(wb_frame, "white_balance_temperature", "Temperature (K)")

        # Power line frequency
        plf_frame = ttk.LabelFrame(right, text="Anti-Flicker", padding=6)
        plf_frame.pack(fill="x", pady=(0, 8))

        self._plf_var = tk.IntVar(value=self.state.power_line_frequency)
        for val, label in ((0, "Off"), (1, "50 Hz"), (2, "60 Hz")):
            ttk.Radiobutton(
                plf_frame, text=label, value=val,
                variable=self._plf_var,
                command=lambda v=val: self._on_plf_change(v),
            ).pack(side="left", padx=6)

        # Save button
        ttk.Button(
            right, text="💾  Save to JSON",
            command=self._save_config,
        ).pack(fill="x", pady=(4, 0), ipady=6)

        self._status = tk.StringVar(value="")
        tk.Label(right, textvariable=self._status, fg="#2a9d2a",
                 font=("monospace", 9)).pack(pady=(4, 0))

        # Reflect current state into widgets
        self._refresh_widgets()

    def _add_slider(self, parent, field: str, label: str):
        mn, mx, step = CTRL_RANGES[field]
        current = getattr(self.state, field)

        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)

        ttk.Label(row, text=f"{label:<20}", width=20).pack(side="left")

        var = tk.IntVar(value=current)
        self._sliders[field] = var

        val_label = ttk.Label(row, text=f"{current:>5}", width=5)

        scale = ttk.Scale(
            row, from_=mn, to=mx, orient="horizontal", length=220,
            variable=var,
            command=lambda v, f=field, lbl=val_label: self._on_slider(f, v, lbl),
        )
        scale.pack(side="left", padx=4)
        val_label.pack(side="left")

        self._slider_widgets[field] = scale

    # ── Event handlers ────────────────────────────────────────────────────────

    def _on_slider(self, field: str, raw_value: str, val_label: ttk.Label):
        mn, mx, step = CTRL_RANGES[field]
        value = int(round(float(raw_value) / step) * step)
        value = max(mn, min(mx, value))
        val_label.config(text=f"{value:>5}")
        setattr(self.state, field, value)
        apply_ctrl(self.device, field, value)

    def _on_bool_change(self, field: str, var: tk.BooleanVar):
        value = var.get()
        setattr(self.state, field, value)
        apply_ctrl(self.device, field, value)
        self._update_dependent_states()

    def _on_plf_change(self, value: int):
        self.state.power_line_frequency = value
        v4l2_set(self.device, "power_line_frequency", value)

    def _on_mode_change(self):
        mode = self._mode_var.get()
        self.state.mode = mode
        if mode in MODE_PRESETS:
            preset = MODE_PRESETS[mode]
            # Copy preset fields into state (keep non-preset fields as-is)
            for field, val in asdict(preset).items():
                setattr(self.state, field, val)
            # Apply every preset control to hardware
            for field, val in asdict(preset).items():
                if field == "mode":
                    continue
                apply_ctrl(self.device, field, val)
        self._refresh_widgets()

    # ── Widget sync ───────────────────────────────────────────────────────────

    def _refresh_widgets(self):
        """Push current state into all widgets."""
        for field, var in self._sliders.items():
            var.set(getattr(self.state, field))
        self._auto_exp_var.set(self.state.auto_exposure)
        self._dyn_fps_var.set(self.state.exposure_dynamic_framerate)
        self._wb_auto_var.set(self.state.white_balance_auto)
        self._plf_var.set(self.state.power_line_frequency)
        self._update_dependent_states()

    def _update_dependent_states(self):
        """Grey out controls that are inactive (e.g., manual exposure time when auto is on)."""
        exp_state = "disabled" if self.state.auto_exposure else "normal"
        if "exposure_time" in self._slider_widgets:
            self._slider_widgets["exposure_time"].config(state=exp_state)

        wb_state = "disabled" if self.state.white_balance_auto else "normal"
        if "white_balance_temperature" in self._slider_widgets:
            self._slider_widgets["white_balance_temperature"].config(state=wb_state)

    # ── Preview update ────────────────────────────────────────────────────────

    def _schedule_preview(self):
        self._update_preview()

    def _update_preview(self):
        # Reschedule first so updates always continue even if rendering fails
        self.root.after(33, self._update_preview)
        try:
            frame = self.frame_queue.get_nowait()
            img = ImageTk.PhotoImage(Image.fromarray(frame))
            self._preview_label.config(image=img)
            self._preview_label.image = img  # prevent GC
        except queue.Empty:
            pass
        except Exception as e:
            print(f"[preview] {e}", flush=True)

    # ── Save ─────────────────────────────────────────────────────────────────

    def _save_config(self):
        data = {
            "mode":                      self.state.mode,
            "brightness":                self.state.brightness,
            "contrast":                  self.state.contrast,
            "saturation":                self.state.saturation,
            "hue":                       self.state.hue,
            "gamma":                     self.state.gamma,
            "gain":                      self.state.gain,
            "sharpness":                 self.state.sharpness,
            "backlight_compensation":    self.state.backlight_compensation,
            "auto_exposure":             self.state.auto_exposure,
            "exposure_time":             self.state.exposure_time,
            "exposure_dynamic_framerate":self.state.exposure_dynamic_framerate,
            "white_balance_auto":        self.state.white_balance_auto,
            "white_balance_temperature": self.state.white_balance_temperature,
            "power_line_frequency":      self.state.power_line_frequency,
        }
        self.config_path.write_text(json.dumps(data, indent=2))
        self._status.set(f"Saved → {self.config_path.name}")
        self.root.after(3000, lambda: self._status.set(""))

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_close(self):
        self._capture.stop()
        self._capture.release()   # release V4L2 before process exits
        self.root.destroy()


# ── Config loading ────────────────────────────────────────────────────────────

def load_state(path: Optional[Path]) -> CameraState:
    state = CameraState()
    if path and path.exists():
        try:
            data = json.loads(path.read_text())
            for k, v in data.items():
                if hasattr(state, k):
                    setattr(state, k, v)
            print(f"Loaded config from {path}")
        except Exception as e:
            print(f"Could not load {path}: {e}")
    return state


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Arducam camera configuration GUI")
    p.add_argument("--config",        metavar="FILE", help="JSON config to load/save")
    p.add_argument("--camera-index",  type=int, default=_resolve_index())
    args = p.parse_args()

    device = f"/dev/video{args.camera_index}"
    config_path = Path(args.config) if args.config else CONFIG_FILE
    state = load_state(config_path)

    root = tk.Tk()
    app = ConfigGUI(root, device, args.camera_index, state, config_path)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
