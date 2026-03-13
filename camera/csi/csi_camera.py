"""CSI camera capture via nvarguscamerasrc/GStreamer + OpenCV.

Usage:
    python3 csi_camera.py [--config csi_camera.json] [options]

Extend by registering frame hooks:
    camera = CSICamera(config)
    camera.add_frame_hook(my_fn)   # fn(frame: np.ndarray) -> Optional[np.ndarray]
    camera.run()
"""

import argparse
import dataclasses
import json
import logging
import signal
import sys
import threading
import time
from typing import Callable, List, Optional

import cv2
import numpy as np


# ── Exceptions ────────────────────────────────────────────────────────────────

class CameraOpenError(RuntimeError):
    pass


# ── Config ────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class CameraConfig:
    # Capture
    sensor_id: int = 0
    capture_width: int = 1920
    capture_height: int = 1080
    framerate: int = 30
    flip_method: int = 0
    drop_frames: bool = False

    # Display
    display_width: int = 960
    display_height: int = 540
    window_title: str = "CSI Camera"
    headless: bool = False

    # Robustness
    max_open_retries: int = 3
    retry_delay_s: float = 1.0


# ── Pipeline builder ──────────────────────────────────────────────────────────

def gstreamer_pipeline(cfg: CameraConfig) -> str:
    drop = " drop=True" if cfg.drop_frames else ""
    return (
        f"nvarguscamerasrc sensor-id={cfg.sensor_id} ! "
        f"video/x-raw(memory:NVMM), width=(int){cfg.capture_width}, "
        f"height=(int){cfg.capture_height}, framerate=(fraction){cfg.framerate}/1 ! "
        f"nvvidconv flip-method={cfg.flip_method} ! "
        f"video/x-raw, width=(int){cfg.display_width}, height=(int){cfg.display_height}, "
        f"format=(string)BGRx ! "
        f"videoconvert ! "
        f"video/x-raw, format=(string)BGR ! appsink{drop}"
    )


# ── Camera class ──────────────────────────────────────────────────────────────

class CSICamera:
    def __init__(self, config: CameraConfig) -> None:
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self._cap: Optional[cv2.VideoCapture] = None
        self._stop_event = threading.Event()
        self._frame_hooks: List[Callable[[np.ndarray], Optional[np.ndarray]]] = []

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
            self._loop()
            return 0
        except CameraOpenError as exc:
            self.logger.error("%s", exc)
            return 1
        finally:
            self._close()

    # ── Private ───────────────────────────────────────────────────────────────

    def _open(self) -> None:
        pipeline = gstreamer_pipeline(self.config)
        self.logger.debug("GStreamer pipeline: %s", pipeline)

        for attempt in range(1, self.config.max_open_retries + 1):
            self.logger.info("Opening CSI camera (attempt %d/%d)...", attempt, self.config.max_open_retries)
            cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
            if cap.isOpened():
                self._cap = cap
                self.logger.info(
                    "CSI camera opened: sensor=%d %dx%d @ %dfps",
                    self.config.sensor_id,
                    self.config.capture_width,
                    self.config.capture_height,
                    self.config.framerate,
                )
                return
            cap.release()
            if attempt < self.config.max_open_retries:
                self.logger.warning("Open failed, retrying in %.1fs...", self.config.retry_delay_s)
                time.sleep(self.config.retry_delay_s)

        raise CameraOpenError(
            f"Could not open CSI camera after {self.config.max_open_retries} attempts. "
            "Check that nvargus-daemon is running: sudo systemctl restart nvargus-daemon"
        )

    def _loop(self) -> None:
        cfg = self.config
        if not cfg.headless:
            cv2.namedWindow(cfg.window_title, cv2.WINDOW_AUTOSIZE)

        self.logger.info("Capture running. Press q or ESC to quit.")

        while not self._stop_event.is_set():
            ret, frame = self._cap.read()
            if not ret:
                self.logger.warning("Empty frame received, skipping.")
                continue

            frame = self._process_frame(frame)

            if not cfg.headless:
                if cv2.getWindowProperty(cfg.window_title, cv2.WND_PROP_AUTOSIZE) < 0:
                    break
                cv2.imshow(cfg.window_title, frame)
                if self._handle_keypress(cv2.waitKey(10) & 0xFF):
                    break
            else:
                time.sleep(1.0 / cfg.framerate)

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
        return key_code in (27, ord("q"))  # ESC or q


# ── Config helpers ────────────────────────────────────────────────────────────

def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(name)-20s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stderr,
    )


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="CSI camera viewer (IMX219 / nvarguscamerasrc)")
    p.add_argument("--config", metavar="FILE", help="JSON config file")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    p.add_argument("--sensor-id", type=int)
    p.add_argument("--capture-width", type=int)
    p.add_argument("--capture-height", type=int)
    p.add_argument("--framerate", type=int)
    p.add_argument("--flip-method", type=int, choices=range(7))
    p.add_argument("--display-width", type=int)
    p.add_argument("--display-height", type=int)
    p.add_argument("--headless", action="store_true", default=None)
    p.add_argument("--max-open-retries", type=int)
    return p.parse_args()


def _load_config(args: argparse.Namespace) -> CameraConfig:
    config = CameraConfig()

    if args.config:
        _apply_json(config, args.config)

    # CLI overrides (only non-None values)
    mapping = {
        "sensor_id": args.sensor_id,
        "capture_width": args.capture_width,
        "capture_height": args.capture_height,
        "framerate": args.framerate,
        "flip_method": args.flip_method,
        "display_width": args.display_width,
        "display_height": args.display_height,
        "headless": args.headless,
        "max_open_retries": args.max_open_retries,
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
    camera = CSICamera(config)

    def _on_signal(signum, _frame):
        logging.getLogger("main").info("Signal %d received, shutting down...", signum)
        camera.stop()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    return camera.run()


if __name__ == "__main__":
    sys.exit(main())
