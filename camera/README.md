# Camera

CSI and USB camera capture programs for the Jetson.

## Structure

```
camera/
├── csi/
│   ├── csi_camera.py   IMX219 via GStreamer / nvarguscamerasrc
│   └── README.md       Sensor specs, modes, controls
└── usb/
    ├── usb_camera.py   USB UVC via V4L2
    └── README.md       Formats, resolutions, controls
```

## Usage

```bash
# CSI
python3 csi/csi_camera.py

# USB
python3 usb/usb_camera.py

# With options
python3 csi/csi_camera.py --flip-method 2 --framerate 21 --capture-width 3280 --capture-height 2464
python3 usb/usb_camera.py --fourcc YUYV --capture-width 1280 --capture-height 720

# Headless (no window)
python3 csi/csi_camera.py --headless

# Debug logging
python3 csi/csi_camera.py --log-level DEBUG

# Config file
python3 csi/csi_camera.py --config csi_camera.json
```

## Config files

All options can be set via JSON. CLI args take precedence over the file.

`csi_camera.json` example:
```json
{
    "sensor_id": 0,
    "capture_width": 1920,
    "capture_height": 1080,
    "framerate": 30,
    "flip_method": 0,
    "display_width": 960,
    "display_height": 540,
    "headless": false
}
```

`usb_camera.json` example:
```json
{
    "camera_index": 1,
    "fourcc": "MJPG",
    "capture_width": 1920,
    "capture_height": 1080,
    "framerate": 30,
    "headless": false
}
```

## Troubleshooting

**CSI: `Failed to create CaptureSession`**
```bash
sudo systemctl restart nvargus-daemon
```

**USB: resolution mismatch warning** — the camera fell back to what it supports. Check with:
```bash
v4l2-ctl -d /dev/video1 --list-formats-ext
```

## IMX219 Sensor Modes

| Resolution  | Max FPS |
|-------------|---------|
| 3280 x 2464 | 21      |
| 3280 x 1848 | 28      |
| 1920 x 1080 | 30      |
| 1640 x 1232 | 30      |
| 1280 x 720  | 60      |

## Extending with frame hooks

```python
from csi_camera import CSICamera, CameraConfig

def my_overlay(frame):
    # modify frame and return it, or return None to pass through
    return frame

camera = CSICamera(CameraConfig())
camera.add_frame_hook(my_overlay)
camera.run()
```
