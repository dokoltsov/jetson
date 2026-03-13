# Camera Selection — Bioreactor Plant Analytics

24/7 plant monitoring in a grow room. Jetson performs growth tracking, stress detection, NDVI.

## What matters here

| Priority | Reason |
|----------|--------|
| **Spectral accuracy** | Chlorophyll stress shifts red/green ratio; NDVI requires NIR at ~850 nm |
| **12-bit raw output** | Preserves subtle color gradients lost in 8-bit JPEG |
| **Pixel size** | Larger pixels → more photons → better signal in grow-room light |
| **CSI over USB** | Zero-copy GPU path via Argus ISP; no USB disconnect failures in 24/7 use |

---

## Cameras

### Currently installed

| | IMX219 (CSI) | Arducam USB |
|-|---|---|
| **Sensor** | Sony IMX219 | Microdia Vitade AF |
| **Resolution** | 8 MP | ~2 MP |
| **Pixel size** | 1.12 µm | unknown |
| **Raw** | 10-bit | MJPG compressed |
| **Interface** | CSI-2 (Argus ISP) | USB 3.0 UVC |
| **IR cut** | Fixed (hardware) | Motorized day/night |
| **NDVI** | ✗ | ✗ |
| **Links** | [Datasheet](https://www.raspberrypi.com/documentation/accessories/camera.html) | — |

IMX219 is fine for visible-spectrum color analysis. Neither camera can do NDVI.
The Arducam USB is unreliable for permanent 24/7 installation.

---

### Recommended replacements / additions

#### [Sony IMX477](https://www.arducam.com/product/arducam-high-quality-camera-for-jetson-nano-and-xavier-nx-12-3mp-m12-mount/) — best single-camera upgrade
12.3 MP · 1.55 µm pixels · **12-bit raw** · CSI-2 · ~$65

The 12-bit raw and larger pixels immediately improve RGB stress detection over the IMX219.
IR cut filter is physically removable — enables NDVI with a dual-band filter add-on.
Proven in long-term deployments. Best color fidelity in this list.

#### [Sony IMX708](https://www.arducam.com/product/arducam-12mp-imx708-camera-module-with-m12-lens-for-raspberry-pi/) — budget alternative
12 MP · 1.4 µm pixels · 10-bit raw · CSI-2 · HDR mode · ~$30

Similar to IMX477 but 10-bit raw and slightly smaller pixels. HDR is useful if grow lights
create harsh shadows. Choose IMX477 if NDVI is a priority (12-bit raw matters for that math).

#### [OV9281 NoIR](https://www.arducam.com/product/arducam-1mp-ov9281-mipi-camera-module-for-nvidia-jetson-nano-xavier-nx-global-shutter-monochrome/) — NIR channel for dual-camera NDVI
1 MP · ~3 µm pixels · global shutter · monochrome · CSI-2 · ~$35

No color, low resolution — useless alone for plant analytics. Paired with an IMX477, it
becomes the NIR channel: IMX477 captures RGB, OV9281 captures NIR proxy through a
[dual-band filter](https://midopt.com/filters/db550-850/). OpenCV aligns frames → NDVI.

#### [IMX327 Starvis](https://www.arducam.com/product/arducam-2mp-low-light-wdr-usb-camera-module-for-computer-2mp-starvis-imx327-uvc-usb2-0-webcam-board-with-case-without-microphone/) — ultra-low-light fallback
2 MP · 2.9 µm pixels · ~100 dB dynamic range · CSI-2 · ~$65

Sony Starvis sensor designed for surveillance: usable at 0.18 lux. Useful if the grow room
goes fully dark at night. Industrial thermal rating (-20°C to +80°C). Lower resolution limits
growth detail — use as a night fallback alongside an IMX477, not as primary.

---

### Professional multispectral (if publishing research)

| Camera | Bands | NDVI accuracy | Cost | Jetson integration |
|--------|-------|---------------|------|--------------------|
| [MicaSense RedEdge-P](https://micasense.com/rededge-p/) | Blue, Green, Red, Red Edge, NIR | Calibrated, citable | ~$5,000 | USB (custom driver) |
| [Sentera 6X](https://sentera.com/products/6x-multispectral-sensor/) | 5 multispectral + 20MP RGB | Calibrated, citable | ~$3,000 | USB (custom driver) |

Both require custom USB integration on Jetson and are designed for drone surveys over fields.
Overkill for a single bioreactor unless the data needs to be publication-grade.

---

### Thermal (supplementary)

Canopy temperature tracks water stress and disease before it's visible in RGB.

| Camera | Resolution | Interface | Sensitivity | Cost | Notes |
|--------|-----------|-----------|-------------|------|-------|
| [FLIR Lepton 3.5](https://www.flir.com/products/lepton/?model=500-0763-01) | 160×120 | SPI (GPIO) | <50 mK | ~$200 | Best spatial resolution; SPI setup required |
| [AMG8833](https://www.adafruit.com/product/3538) | 8×8 | I2C (GPIO) | ~1°C | ~$40 | Easiest integration; only for hotspot detection |

Neither replaces an RGB or NIR camera — use as an additional analytics channel.

---

## NDVI

**NDVI = (NIR − Red) / (NIR + Red)**

Plants reflect NIR (~850 nm) strongly and absorb Red (~670 nm) during photosynthesis.
Healthy = high NIR, low Red → NDVI near 1.0. Stressed = NDVI drops.

| NDVI | Meaning |
|------|---------|
| 0.6 – 1.0 | Healthy, active photosynthesis |
| 0.3 – 0.6 | Moderate stress |
| 0.0 – 0.3 | Severe stress / senescence |
| < 0.0 | Non-vegetation |

Standard cameras block NIR with an IR cut filter. To get NDVI:

1. **Remove IR cut from IMX477** + add [dual-band filter 550/850 nm](https://midopt.com/filters/db550-850/) (~$25).
   One camera captures both channels. NDVI computed via channel math in OpenCV.

2. **Dual-camera** — IMX477 (RGB, IR cut in) + OV9281 NoIR (NIR channel) + filter.
   More accurate; requires frame alignment. ~95% correlation vs. professional multispectral
   after calibration with a [grey reference panel](https://www.spectralpanel.com/).

3. **Professional multispectral** (MicaSense/Sentera) — calibrated, citable, expensive.

---

## Recommended build

| Phase | Add | Cost | Unlocks |
|-------|-----|------|---------|
| **1** — now | [Arducam IMX477 CSI](https://www.arducam.com/product/arducam-high-quality-camera-for-jetson-nano-and-xavier-nx-12-3mp-m12-mount/) | ~$65 | 12-bit raw, better color, NDVI-ready sensor |
| **2** — next | [OV9281 NoIR CSI](https://www.arducam.com/product/arducam-1mp-ov9281-mipi-camera-module-for-nvidia-jetson-nano-xavier-nx-global-shutter-monochrome/) + [dual-band filter](https://midopt.com/filters/db550-850/) | ~$60 | True NDVI via dual-camera pipeline |
| **3** — optional | [AMG8833](https://www.adafruit.com/product/3538) via I2C | ~$40 | Canopy temperature → early drought/disease |
| **4** — research | [Sentera 6X](https://sentera.com/products/6x-multispectral-sensor/) | ~$3,000 | Calibrated multispectral, citable NDVI |
