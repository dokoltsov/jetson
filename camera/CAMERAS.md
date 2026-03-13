# Camera Selection for Bioreactor Plant Analytics

Permanent 24/7 plant monitoring in a grow room, with Jetson performing plant health analytics:
growth tracking, stress detection, and NDVI.

---

## What makes a camera suitable here

| Priority | Why it matters |
|----------|---------------|
| **Spectral accuracy** | Chlorophyll stress shifts the red/green ratio; NDVI requires NIR at ~850 nm |
| **Color fidelity** | Yellowing, purpling, browning all show in different channels — accurate colors = reliable analytics |
| **Raw output bit depth** | 12-bit raw preserves subtle color gradients lost in 8-bit JPEG |
| **Low-light performance** | Grow lights may cycle off; larger pixels = more photons per exposure |
| **CSI over USB** | CSI-2 gives zero-copy GPU path via Argus ISP; no USB reconnect failures in 24/7 use |
| **24/7 thermal stability** | Continuous operation at grow-room temps (18–28°C); CSI modules more stable than USB |

---

## Camera comparison

### Currently installed

#### IMX219 — Sony 8MP CSI (primary)
| Spec | Value |
|------|-------|
| Resolution | 8 MP (3280×2464) |
| Pixel size | 1.12 µm — small; noisier in low light |
| Raw output | 10-bit Bayer |
| Interface | CSI-2 (Argus ISP, zero-copy GPU) |
| IR cut filter | Yes (hardware, fixed) |
| Low-light | Moderate |
| NDVI | No — IR cut fixed; would need hardware mod + external filter |
| Cost | ~$25 |

Good for visible-spectrum color analysis and growth tracking. Insufficient for NDVI without modification.

---

#### Arducam Day/Night USB — 0c45:6366 (secondary)
| Spec | Value |
|------|-------|
| Resolution | ~2 MP (1920×1080 MJPG) |
| Pixel size | Unknown (Microdia Vitade AF chipset) |
| Interface | USB 3.0 UVC — MJPG compressed |
| IR cut filter | Motorized (day/night switching) |
| Low-light | Unknown sensor; moderate |
| NDVI | No — switches between full-color or full-grayscale; no simultaneous NIR+RGB |
| Cost | ~$50 |

Useful as a day/night fallback but not suitable for plant analytics or NDVI. USB reliability
is worse than CSI for 24/7 deployments (disconnects, bandwidth limits).

---

### Recommended upgrades

#### IMX477 — Sony 12.3MP CSI (best single-camera upgrade)
| Spec | Value |
|------|-------|
| Resolution | 12.3 MP (4056×3040) |
| Pixel size | 1.55 µm — 39% larger than IMX219; significantly better low-light |
| Raw output | **12-bit** — best in class for post-processing |
| Interface | CSI-2 (Argus ISP via Arducam adapter) |
| IR cut filter | Yes, but **removable** — enables NIR imaging with external filter |
| Low-light | Excellent (back-illuminated, stacked) |
| NDVI | Yes with filter mod: remove IR cut + add dual-band (550/850 nm) filter |
| Reliability | Proven in Pi ecosystem; extensive 24/7 field use |
| Cost | ~$65 |

**Best single-camera choice for this use case.** The 12-bit raw output preserves subtle color
shifts that indicate early stress. Pixel size means better signal in low grow-room light.

---

#### IMX708 — Sony 12MP CSI (budget alternative to IMX477)
| Spec | Value |
|------|-------|
| Resolution | 12 MP (4608×2592) |
| Pixel size | 1.4 µm — slightly smaller than IMX477 |
| Raw output | 10-bit |
| Interface | CSI-2 (Argus ISP via Arducam adapter) |
| HDR mode | Yes (useful for high-contrast grow-room lighting) |
| NDVI | Yes with filter mod (same as IMX477) |
| Cost | ~$30 |

Good budget alternative. Choose IMX477 if you want 12-bit raw for NDVI; choose IMX708 if
cost matters and HDR is useful for your lighting setup.

---

#### OV9281 — OmniVision 1MP Global Shutter Monochrome CSI
| Spec | Value |
|------|-------|
| Resolution | 1 MP (1280×800) — low |
| Pixel size | ~3 µm — excellent light gathering |
| Shutter | **Global** — no rolling shutter artifacts |
| Color | **Monochrome only** — no color analysis |
| Interface | CSI-2 (Arducam adapter; no Argus ISP) |
| Spectral response | Panchromatic (all visible + NIR) |
| NDVI | Only in dual-camera setup with a filter |
| Cost | ~$35 |

Not useful alone for plant analytics (no color, low resolution). Very useful as the **NIR
channel** in a dual-camera NDVI setup paired with an IMX477.

---

#### IMX290 / IMX327 Starvis — Sony 2MP CSI (ultra-low-light)
| Spec | Value |
|------|-------|
| Resolution | 2 MP (1920×1080) |
| Pixel size | ~2.9 µm — large; excellent photon capture |
| Dynamic range | ~100 dB (IMX327 > IMX290) |
| Low-light | **Extraordinary** — 0.18 lux usable |
| Color | Monochrome standard; color variant exists |
| NDVI | Color variant possible with filter mod |
| 24/7 reliability | Proven — industrial/surveillance grade, -20°C to +80°C tested |
| Cost | ~$65 |

Best choice if the grow room goes fully dark at night and you want usable frames with zero IR
supplemental lighting. Lower resolution limits growth detail. Pairs well with IMX477 as a
24/7 fallback / night camera.

---

### Professional multispectral (if budget allows)

#### MicaSense RedEdge-P
Dedicated 5-band multispectral (Blue, Green, Red, Red Edge 710–800 nm, NIR 860–910 nm).
Radiometrically calibrated — publication-grade NDVI, NDRE, OSAVI out of the box.
Interface: USB (not CSI; requires custom Jetson integration).
Cost: ~$5,000. **Overkill for a single bioreactor. Better for multi-site or research publishing.**

#### Sentera 6X
5 multispectral bands + 20MP RGB. Global shutter. USB/drone integration.
Cost: ~$3,000. Same assessment — excellent sensor, complex Jetson integration, high cost.

---

### Thermal (supplementary)

Thermal adds canopy temperature monitoring — useful for detecting water stress, disease, and
photosynthetic rate changes before they're visible in RGB.

| Camera | Resolution | Interface | Sensitivity | Cost |
|--------|-----------|-----------|-------------|------|
| FLIR Lepton 3.5 | 160×120 | SPI (GPIO) | <50 mK | ~$200 |
| AMG8833 | 8×8 | I2C (GPIO) | ~1°C | ~$40 |
| Seek Thermal | 206×156 | USB | ~0.1°C | ~$150 |

**AMG8833** is the easiest Jetson integration (I2C via GPIO) — adequate for detecting canopy
hotspots despite the low resolution.
**Lepton 3.5** is better for spatial thermal maps but requires SPI setup.
Neither replaces an RGB or multispectral camera — use as a complementary channel.

---

## NDVI explained for this use case

NDVI (Normalized Difference Vegetation Index) = **(NIR − Red) / (NIR + Red)**

Plants strongly reflect NIR (~850 nm) and absorb Red (~670 nm) during photosynthesis.
A healthy plant has high NIR reflectance and low red reflectance → high NDVI (0.6–1.0).
Stressed, senescing, or sparse plants have lower NDVI.

| NDVI range | Meaning |
|------------|---------|
| 0.6 – 1.0 | Healthy, active photosynthesis |
| 0.3 – 0.6 | Moderate stress, reduced vigor |
| 0.0 – 0.3 | Severe stress or senescence |
| < 0.0 | Non-vegetation (substrate, equipment) |

### Getting NDVI from a standard camera

Standard cameras have an IR cut filter that blocks NIR. Options:

1. **Remove the IR cut filter** from an IMX477 + add a dual-band optical filter
   (passes ~550 nm and ~850 nm). The sensor then captures NIR in one Bayer channel
   and visible green in another. NDVI computed in software.
   Cost: ~$20–30 for filter. Accuracy: good.

2. **Dual-camera setup:** IMX477 (RGB, IR cut in) + OV9281 NoIR (no IR cut) + blue/green
   longpass filter. Align frames in software, compute NDVI channel by channel.
   Cost: ~$100 total. Accuracy: ~95% vs. reference multispectral with calibration.

3. **Professional multispectral** (MicaSense/Sentera): Dedicated calibrated bands.
   Cost: $3,000–6,000. Accuracy: publication-grade.

---

## Recommended build for this Jetson

### Phase 1 — now (~$65)
Replace IMX219 with **Arducam IMX477 CSI**.
- Better color accuracy and 12-bit raw immediately improves RGB stress detection
- Growth tracking, chlorophyll color analysis, contour-based size measurement
- Keep Arducam USB as night/fallback

### Phase 2 — next (~$60 more)
Add **OV9281 NoIR CSI** + dual-band filter on Jetson's second CSI lane.
- Enables true NDVI computation
- IMX477 = RGB channel, OV9281 = NIR proxy
- OpenCV frame alignment + NDVI index overlay

### Phase 3 — optional (~$40)
Add **AMG8833 thermal** via I2C GPIO.
- Canopy temperature map
- Early drought/disease detection via thermal anomaly
- Correlates with NDVI for multi-modal plant health score

### Phase 4 — if publishing research (~$3,000+)
Replace dual-camera setup with **Sentera 6X** or **MicaSense RedEdge-P**.
- Calibrated multispectral; citable NDVI/NDRE values
- USB integration with Jetson (custom driver work required)
