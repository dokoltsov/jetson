# USB Camera — Arducam Day/Night

**Arducam Technology Co., Ltd.** — `0c45:6366` (Microdia Vitade AF chipset)
UVC-compliant. Connected via USB 3.0. Includes a built-in microphone.

## Device info

| Property | Value |
|----------|-------|
| Manufacturer | Arducam Technology Co., Ltd. |
| USB ID | 0c45:6366 |
| Driver | uvcvideo |
| Interface | USB 3.0 (`3610000.usb-2.3`) |
| Video device | `/dev/video1`, `/dev/video2` |
| Audio device | `/dev/snd/...` (built-in mic) |
| Serial | SN0001 |

## Day/night capability

The camera has a motorized **IR cut filter** and is designed to switch between:

| Mode | IR cut filter | Saturation | Gain | Exposure |
|------|--------------|------------|------|----------|
| Day  | Engaged (blocks IR) | Full color | Low (auto) | Auto |
| Night | Removed (passes IR) | 0 (grayscale) | Max (100) | Manual, max |
| Auto | Camera decides | Camera default | Auto | Auto |

The IR cut filter is controlled via the **UVC Extension Unit** (GUID `{28f03370-6311-4a2e-ba2c-6890eb334016}`, 32 controls) using `uvcdynctrl`. If `uvcdynctrl` is unavailable, the program applies the V4L2 image control preset (saturation, gain, exposure) but the physical filter must switch on its own.

## Supported formats and resolutions

### MJPG (recommended — compressed, full frame rate)

| Resolution  | FPS |
|-------------|-----|
| 1920 × 1080 | 30  |
| 1280 × 1024 | 30  |
| 1280 × 960  | 30  |
| 1280 × 720  | 30  |
| 1024 × 768  | 30  |
| 800 × 600   | 30  |
| 640 × 480   | 30  |
| 352 × 288   | 30  |
| 320 × 240   | 30  |

### YUYV (uncompressed — limited by USB bandwidth)

| Resolution  | FPS |
|-------------|-----|
| 1920 × 1080 | 5   |
| 1280 × 720  | 10  |
| 800 × 600   | 20  |
| 640 × 480   | 15  |
| 320 × 240   | 30  |

## Image controls

| Control | Range | Default | Notes |
|---------|-------|---------|-------|
| Brightness | -64 – 64 | 0 | |
| Contrast | 0 – 64 | 32 | |
| Saturation | 0 – 128 | 64 | 0 = grayscale (used in night mode) |
| Hue | -40 – 40 | 0 | |
| Gain | 0 – 100 | 0 | |
| Gamma | 72 – 500 | 100 | |
| Sharpness | 0 – 14 | 10 | |
| White balance auto | on/off | on | |
| White balance temperature | 2800 – 6500 K | 4600 K | Active when AWB off |
| Backlight compensation | 0 – 160 | 80 | |
| Auto exposure | aperture priority / manual | aperture priority | |
| Exposure time | 1 – 5000 | 157 | Active when auto exposure off |
| Exposure dynamic framerate | on/off | on | Allow FPS drop for exposure |
| Power line frequency | 0/1/2 | 1 (50 Hz) | Anti-flicker |

## Launch

```bash
# Default (auto mode)
python3 usb_camera.py

# Day mode
python3 usb_camera.py --mode day

# Night mode
python3 usb_camera.py --mode night

# Night mode, override gain manually
python3 usb_camera.py --mode night --gain 80

# Manual exposure, specific resolution
python3 usb_camera.py --no-auto-exposure --exposure-time 2000 --capture-width 1280 --capture-height 720

# Config file
python3 usb_camera.py --config usb_camera.json

# Debug (shows all v4l2-ctl calls)
python3 usb_camera.py --mode night --log-level DEBUG
```

## Config file example

```json
{
    "mode": "night",
    "capture_width": 1280,
    "capture_height": 720,
    "framerate": 30,
    "fourcc": "MJPG",
    "gain": 80,
    "exposure_time": 3000
}
```

## Notes

- Use **MJPG** for anything above 640×480 to stay within USB bandwidth.
- In **night mode**, `exposure_dynamic_framerate` is disabled to keep consistent frame timing. The camera will not drop below the configured FPS to compensate for low light — gain and exposure time handle that instead.
- The camera includes a **built-in microphone** on the same USB device. It appears as a separate ALSA device and is not handled by this program.
- If the negotiated resolution differs from the request, a warning is logged. Check supported modes with: `v4l2-ctl -d /dev/video1 --list-formats-ext`
