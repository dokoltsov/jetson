"""Arducam day/night USB camera capture via V4L2 + OpenCV.

Hardware: Arducam 0c45:6366 (Microdia Vitade AF chipset)
Device:   /dev/video1  (UVC, MJPG/YUYV)

Usage:
    python3 usb_camera.py [--mode night] [--config usb_camera.json] [options]

Extend by registering frame hooks:
    camera = USBCamera(config)
    camera.add_frame_hook(my_fn)   # fn(frame: np.ndarray) -> Optional[np.ndarray]
    camera.run()
"""

import argparse
import dataclasses
import enum
import json
import logging
import signal
import subprocess
import sys
import threading
import time
from typing import Callable, List, Optional

import cv2
import numpy as np


# ── Device resolution ─────────────────────────────────────────────────────────

_BY_ID = "/dev/v4l/by-id/usb-Arducam_Technology_Co.__Ltd._USB_Camera_SN0001-video-index0"

def _resolve_camera_index(fallback: int = 1) -> int:
    """Return the current integer index of the Arducam via its stable by-id symlink.

    The index changes after a USB reset; the symlink always points to the right device.
    Falls back to `fallback` if the symlink is not present.
    """
    import os
    try:
        target = os.path.realpath(_BY_ID)          # e.g. /dev/video2
        return int(target.replace("/dev/video", ""))
    except Exception:
        return fallback


# ── Exceptions ────────────────────────────────────────────────────────────────

class CameraOpenError(RuntimeError):
    pass


# ── Mode ──────────────────────────────────────────────────────────────────────

class CameraMode(enum.Enum):
    AUTO  = "auto"   # camera defaults, fully automatic
    DAY   = "day"    # color, auto exposure/WB, IR cut filter engaged
    NIGHT = "night"  # grayscale, max gain, long exposure, IR cut filter removed


# ── Config ────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class CameraConfig:
    # Device
    camera_index: int = dataclasses.field(default_factory=_resolve_camera_index)
    fourcc: str = "MJPG"

    # Capture
    capture_width: int = 1920
    capture_height: int = 1080
    framerate: int = 30
    buffer_size: int = 1        # minimize latency

    # Day/night mode — overrides individual image controls below
    mode: str = CameraMode.AUTO.value   # "auto" | "day" | "night"

    # Image controls (None = leave at camera default / mode preset)
    brightness: Optional[int] = None            # -64 to 64
    contrast: Optional[int] = None              # 0 to 64
    saturation: Optional[int] = None            # 0 to 128  (0 = grayscale)
    hue: Optional[int] = None                   # -40 to 40
    gamma: Optional[int] = None                 # 72 to 500
    gain: Optional[int] = None                  # 0 to 100
    sharpness: Optional[int] = None             # 0 to 14
    backlight_compensation: Optional[int] = None  # 0 to 160
    white_balance_auto: Optional[bool] = None
    white_balance_temperature: Optional[int] = None  # 2800 to 6500 K
    auto_exposure: Optional[bool] = None        # True = aperture priority, False = manual
    exposure_time: Optional[int] = None         # 1 to 5000 (active when auto_exposure=False)
    exposure_dynamic_framerate: Optional[bool] = None  # allow FPS drop for exposure
    power_line_frequency: Optional[int] = None  # 0=off, 1=50Hz, 2=60Hz

    # Warmup
    warmup_sleep_s: float = 1.0
    warmup_frames: int = 5

    # Robustness
    max_consecutive_failures: int = 10
    retry_sleep_s: float = 0.1

    # Display
    window_title: str = "Arducam"
    headless: bool = False


# Mode presets — applied before any per-field overrides in CameraConfig
_MODE_PRESETS: dict = {
    CameraMode.DAY: {
        "auto_exposure": True,
        "exposure_dynamic_framerate": True,
        "white_balance_auto": True,
        "saturation": 64,           # normal color
        "gain": 0,
        "backlight_compensation": 80,
    },
    CameraMode.NIGHT: {
        "auto_exposure": False,
        "exposure_time": 5000,      # max exposure
        "exposure_dynamic_framerate": False,  # keep consistent FPS
        "white_balance_auto": False,
        "white_balance_temperature": 4600,
        "saturation": 0,            # grayscale — IR illumination has no color
        "gain": 100,                # max analog gain
        "backlight_compensation": 0,
    },
}

# Maps CameraConfig field names to v4l2-ctl control names
_V4L2_CTRL_MAP = {
    "brightness":               "brightness",
    "contrast":                 "contrast",
    "saturation":               "saturation",
    "hue":                      "hue",
    "gamma":                    "gamma",
    "gain":                     "gain",
    "sharpness":                "sharpness",
    "backlight_compensation":   "backlight_compensation",
    "white_balance_temperature":"white_balance_temperature",
    "exposure_time":            "exposure_time_absolute",
    "power_line_frequency":     "power_line_frequency",
}

# Boolean controls use integer 1/0 in v4l2-ctl
_V4L2_BOOL_MAP = {
    "white_balance_auto":          "white_balance_automatic",
    "exposure_dynamic_framerate":  "exposure_dynamic_framerate",
    # auto_exposure maps to a menu: 1=manual, 3=aperture priority
}


# ── Camera class ──────────────────────────────────────────────────────────────

class USBCamera:
    def __init__(self, config: CameraConfig) -> None:
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self._cap: Optional[cv2.VideoCapture] = None
        self._stop_event = threading.Event()
        self._frame_hooks: List[Callable[[np.ndarray], Optional[np.ndarray]]] = []
        self._device = f"/dev/video{config.camera_index}"

    def add_frame_hook(self, fn: Callable[[np.ndarray], Optional[np.ndarray]]) -> None:
        """Register a frame processing callback.

        fn receives the current frame and may return a modified frame or None
        to pass the frame through unchanged.
        """
        self._frame_hooks.append(fn)

    def stop(self) -> None:
        """Signal the capture loop to exit (thread-safe)."""
        self._stop_event.set()

    def run(self) -> int:
        """Open camera, run capture loop, return exit code (0 = clean, 1 = error)."""
        try:
            self._open()
            # Warmup first: camera-level controls (auto_exposure, white_balance_automatic,
            # exposure_dynamic_framerate) trigger a UVC re-probe if set before streaming
            # and leave the device in a broken state. Applying after warmup is safe.
            self._warmup()
            self._apply_mode()
            self._loop()
            return 0
        except CameraOpenError as exc:
            self.logger.error("%s", exc)
            return 1
        finally:
            self._close()

    # ── Private ───────────────────────────────────────────────────────────────

    def _open(self) -> None:
        cfg = self.config
        self.logger.info("Opening %s (index %d)...", self._device, cfg.camera_index)

        cap = cv2.VideoCapture(cfg.camera_index, cv2.CAP_V4L2)
        if not cap.isOpened():
            raise CameraOpenError(f"Could not open {self._device}")

        # FOURCC must be set before width/height for V4L2 to negotiate correctly
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*cfg.fourcc))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.capture_width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.capture_height)
        cap.set(cv2.CAP_PROP_FPS, cfg.framerate)
        # Night mode uses long exposures (~500ms); BUFFERSIZE=1 corrupts the single
        # queued buffer when v4l2-ctl changes sensor controls after warmup. Use the
        # driver default (4) for night so the buffer queue stays healthy.
        buf = cfg.buffer_size if CameraMode(cfg.mode) != CameraMode.NIGHT else 4
        cap.set(cv2.CAP_PROP_BUFFERSIZE, buf)

        actual_w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = cap.get(cv2.CAP_PROP_FPS)

        self.logger.info(
            "Opened: %dx%d @ %.0ffps %s (requested %dx%d @ %dfps)",
            actual_w, actual_h, actual_fps, cfg.fourcc,
            cfg.capture_width, cfg.capture_height, cfg.framerate,
        )
        if (actual_w, actual_h) != (cfg.capture_width, cfg.capture_height):
            self.logger.warning(
                "Camera negotiated different resolution: %dx%d (requested %dx%d)",
                actual_w, actual_h, cfg.capture_width, cfg.capture_height,
            )

        self._cap = cap

    def _apply_mode(self) -> None:
        """Apply mode preset then any explicit per-field overrides from config."""
        cfg = self.config
        try:
            mode = CameraMode(cfg.mode)
        except ValueError:
            self.logger.warning("Unknown mode %r, using AUTO", cfg.mode)
            mode = CameraMode.AUTO

        controls: dict = {}

        # Layer 1: mode preset
        if mode in _MODE_PRESETS:
            controls.update(_MODE_PRESETS[mode])
            self.logger.info("Applying %s mode preset", mode.value)

        # Layer 2: explicit config fields override the preset
        for field in dataclasses.fields(cfg):
            if field.name in _V4L2_CTRL_MAP or field.name in _V4L2_BOOL_MAP or field.name == "auto_exposure":
                val = getattr(cfg, field.name)
                if val is not None:
                    controls[field.name] = val

        # Apply all resolved controls
        for key, val in controls.items():
            self._set_ctrl(key, val)

        # IR cut filter via UVC extension unit
        if mode == CameraMode.DAY:
            self._set_ir_cut(engaged=True)
        elif mode == CameraMode.NIGHT:
            self._set_ir_cut(engaged=False)

    def _set_ctrl(self, field: str, value) -> None:
        """Set a V4L2 control by CameraConfig field name."""
        if field == "auto_exposure":
            # Maps to a menu: 3=aperture priority (auto), 1=manual
            v4l2_val = 3 if value else 1
            self._v4l2_ctl("auto_exposure", v4l2_val)
        elif field in _V4L2_BOOL_MAP:
            self._v4l2_ctl(_V4L2_BOOL_MAP[field], int(value))
        elif field in _V4L2_CTRL_MAP:
            self._v4l2_ctl(_V4L2_CTRL_MAP[field], int(value))

    def _v4l2_ctl(self, ctrl: str, value: int) -> bool:
        """Set a single v4l2 control. Returns True on success."""
        try:
            subprocess.run(
                ["v4l2-ctl", f"--device={self._device}", f"--set-ctrl={ctrl}={value}"],
                capture_output=True, check=True,
            )
            self.logger.debug("v4l2: %s=%d", ctrl, value)
            return True
        except subprocess.CalledProcessError as exc:
            self.logger.warning("Could not set %s=%d: %s", ctrl, value, exc.stderr.decode().strip())
            return False
        except FileNotFoundError:
            self.logger.warning("v4l2-ctl not found; image controls unavailable")
            return False

    def _set_ir_cut(self, engaged: bool) -> None:
        """Attempt to switch the IR cut filter via the Arducam UVC extension unit.

        Extension unit GUID: {28f03370-6311-4a2e-ba2c-6890eb334016} (32 controls)
        Selector 1 is the IR cut filter on Arducam day/night cameras:
            1 = filter engaged (day mode, blocks IR)
            0 = filter removed (night mode, passes IR)
        This is a best-effort call — failure is logged but does not abort.
        """
        value = 1 if engaged else 0
        label = "engaged (day)" if engaged else "removed (night)"
        try:
            subprocess.run(
                [
                    "uvcdynctrl",
                    "--device", self._device,
                    "--set", "XU IR Cut", str(value),
                ],
                capture_output=True, check=True,
            )
            self.logger.info("IR cut filter %s", label)
        except (subprocess.CalledProcessError, FileNotFoundError):
            # uvcdynctrl not available or XU control name differs — try via v4l2-ctl raw XU
            self.logger.debug(
                "uvcdynctrl unavailable; IR cut filter must be switched manually or via Arducam SDK"
            )

    def _warmup(self) -> None:
        cfg = self.config
        self.logger.info("Warming up (%.1fs + %d frames)...", cfg.warmup_sleep_s, cfg.warmup_frames)
        time.sleep(cfg.warmup_sleep_s)
        for _ in range(cfg.warmup_frames):
            self._cap.read()

    def _loop(self) -> None:
        cfg = self.config
        if not cfg.headless:
            cv2.namedWindow(cfg.window_title, cv2.WINDOW_AUTOSIZE)

        self.logger.info("Capture running. Press q to quit.")
        consecutive_failures = 0

        while not self._stop_event.is_set():
            ret, frame = self._cap.read()
            if not ret:
                consecutive_failures += 1
                self.logger.warning(
                    "Frame grab failed (%d/%d)", consecutive_failures, cfg.max_consecutive_failures
                )
                if consecutive_failures >= cfg.max_consecutive_failures:
                    self.logger.error("Too many consecutive failures, aborting.")
                    break
                time.sleep(cfg.retry_sleep_s)
                continue

            consecutive_failures = 0
            frame = self._process_frame(frame)

            if not cfg.headless:
                cv2.imshow(cfg.window_title, frame)
                if self._handle_keypress(cv2.waitKey(1) & 0xFF):
                    break

    def _process_frame(self, frame: np.ndarray) -> np.ndarray:
        for hook in self._frame_hooks:
            result = hook(frame)
            if result is not None:
                frame = result
        return frame

    def _close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        cv2.destroyAllWindows()
        self.logger.info("Camera released.")

    def _handle_keypress(self, key_code: int) -> bool:
        return key_code == ord("q")


# ── Config helpers ────────────────────────────────────────────────────────────

def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(name)-20s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stderr,
    )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Arducam day/night USB camera (V4L2)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--config",      metavar="FILE", help="JSON config file")
    p.add_argument("--log-level",   default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    # Device / capture
    p.add_argument("--camera-index",   type=int,  help="V4L2 device index")
    p.add_argument("--fourcc",         type=str,  help="Pixel format: MJPG (default) or YUYV")
    p.add_argument("--capture-width",  type=int)
    p.add_argument("--capture-height", type=int)
    p.add_argument("--framerate",      type=int)
    p.add_argument("--headless",       action="store_true", default=None)

    # Day/night mode
    p.add_argument("--mode", choices=["auto", "day", "night"],
                   help="Camera mode preset (day/night applies V4L2 + IR cut settings)")

    # Image controls
    p.add_argument("--brightness",             type=int,  help="-64 to 64")
    p.add_argument("--contrast",               type=int,  help="0 to 64")
    p.add_argument("--saturation",             type=int,  help="0 to 128 (0=grayscale)")
    p.add_argument("--gain",                   type=int,  help="0 to 100")
    p.add_argument("--exposure-time",          type=int,  help="1 to 5000 (manual exposure)")
    p.add_argument("--no-auto-exposure",       action="store_true", help="Enable manual exposure")
    p.add_argument("--no-auto-white-balance",  action="store_true", help="Disable auto white balance")
    p.add_argument("--white-balance-temperature", type=int, help="2800 to 6500 K")
    p.add_argument("--power-line-frequency",   type=int, choices=[0, 1, 2],
                   help="0=off, 1=50Hz, 2=60Hz")

    return p.parse_args()


def _load_config(args: argparse.Namespace) -> CameraConfig:
    config = CameraConfig()

    if args.config:
        _apply_json(config, args.config)

    mapping = {
        "camera_index":              args.camera_index,
        "fourcc":                    args.fourcc,
        "capture_width":             args.capture_width,
        "capture_height":            args.capture_height,
        "framerate":                 args.framerate,
        "headless":                  args.headless if args.headless else None,
        "mode":                      args.mode,
        "brightness":                args.brightness,
        "contrast":                  args.contrast,
        "saturation":                args.saturation,
        "gain":                      args.gain,
        "exposure_time":             args.exposure_time,
        "auto_exposure":             False if args.no_auto_exposure else None,
        "white_balance_auto":        False if args.no_auto_white_balance else None,
        "white_balance_temperature": args.white_balance_temperature,
        "power_line_frequency":      args.power_line_frequency,
    }
    for key, val in mapping.items():
        if val is not None:
            setattr(config, key, val)

    return config


def _apply_json(config: CameraConfig, path: str) -> None:
    log = logging.getLogger("config")
    valid = {f.name for f in dataclasses.fields(config)}
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        log.error("Could not load config file %r: %s", path, exc)
        return
    for key, val in data.items():
        if key in valid:
            setattr(config, key, val)
        else:
            log.warning("Unknown config key ignored: %r", key)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    args = _parse_args()
    _setup_logging(args.log_level)
    config = _load_config(args)
    camera = USBCamera(config)

    def _on_signal(signum, _frame):
        logging.getLogger("main").info("Signal %d received, shutting down...", signum)
        camera.stop()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    return camera.run()


if __name__ == "__main__":
    sys.exit(main())
