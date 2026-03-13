# CSI Camera — IMX219

Sony IMX219 8MP sensor connected via CSI-2 to the Jetson.
Captured through the NVIDIA Argus/GStreamer stack (`nvarguscamerasrc`).

## Sensor specs

| Property | Value |
|----------|-------|
| Sensor | Sony IMX219 |
| Resolution | 8 MP (3280 × 2464) |
| Pixel size | 1.12 µm |
| Shutter | Rolling shutter |
| Interface | CSI-2 (2-lane MIPI) |
| Device | `/dev/video0` |
| Daemon | `nvargus-daemon` |

## Sensor modes

| Resolution  | FPS | Notes |
|-------------|-----|-------|
| 3280 × 2464 | 21  | Full sensor, maximum FOV |
| 3280 × 1848 | 28  | 16:9 crop |
| 1920 × 1080 | 30  | Default mode |
| 1640 × 1232 | 30  | 2× binned, better low light |
| 1280 × 720  | 60  | High frame rate |

## Camera controls (exposed via Argus)

| Control | Range | Notes |
|---------|-------|-------|
| Analog gain | 1.0 – 10.625× | Hardware gain on sensor |
| Exposure | 13 µs – 683 ms | Manual or auto |
| Frame rate | 2 – 30 fps | Per mode max |
| Flip method | 0 – 6 | Rotate/mirror via nvvidconv |
| Sensor mode | 0 – 5 | Selects resolution/fps mode |

## Flip methods

| Value | Transform |
|-------|-----------|
| 0 | None |
| 1 | Counterclockwise 90° |
| 2 | Rotate 180° |
| 3 | Clockwise 90° |
| 4 | Horizontal flip |
| 5 | Upper-right diagonal flip |
| 6 | Vertical flip |
| 7 | Upper-left diagonal flip |

## Pixel format

Raw output from the sensor is **10-bit Bayer (RGGB)** — `RG10`.
The GStreamer pipeline converts it to BGR via `nvvidconv` + `videoconvert` before OpenCV sees it. ISP processing (demosaic, noise reduction, tone mapping) is handled in hardware by the Argus ISP.

## Capabilities

- Hardware ISP (auto white balance, auto exposure, noise reduction, tone mapping)
- Manual exposure and gain control via Argus API
- Zero-copy GPU buffer path via `NVMM` memory
- Supports stereo (dual CSI cameras with `sensor-id=0/1`)
- Low latency capture suitable for real-time CV pipelines

## Launch

```bash
python3 csi_camera.py
python3 csi_camera.py --flip-method 2 --framerate 21 --capture-width 3280 --capture-height 2464
python3 csi_camera.py --log-level DEBUG   # prints the full GStreamer pipeline
```

## Troubleshooting

**`Failed to create CaptureSession`** — restart the Argus daemon:
```bash
sudo systemctl restart nvargus-daemon
```
