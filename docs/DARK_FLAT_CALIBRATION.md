# Dark and Flat-Field Calibration

Instructions for acquiring dark and flat frames used by the spectrometer signal processing pipeline.

---

## 1. Overview

**Dark frame**: Image captured with no light (lens cap on, or light source off). Contains thermal noise and readout bias.

**Flat frame**: Image of uniform illumination. Corrects pixel-to-pixel sensitivity variation and vignetting.

**Formula**: `corrected = (raw - dark) / (flat - dark)`

---

## 2. Prerequisites

- RTSP stream **OFF** (V4L2 device exclusive)
- Camera settings (resolution, pixel format) **identical** to measurement conditions
- Dark: same **shutter** and **gain** as science exposures (or see scaling note below)
- Flat: **unsaturated** (no pixels at max value)

---

## 3. Acquiring Dark Frames

### 3.1 Procedure

1. **Block all light** to the spectrometer (lens cap, cover slit, or turn off light source).
2. Set camera to the **same shutter and gain** you will use for measurements.
3. Capture **10–100 frames** and average them to reduce random noise.
4. Save the averaged frame as `dark.npy` (NumPy format).

### 3.2 When to Recalibrate

- After changing shutter or gain
- Periodically (e.g. weekly) if temperature varies
- If hot pixels appear or change

### 3.3 Shutter Mismatch

If you cannot match shutter exactly, dark can be scaled: `dark_scaled = dark * (t_science / t_dark)`. This is approximate; prefer matching exposure when possible.

---

## 4. Acquiring Flat Frames
In practice may be challenging to apply in spectrometer hardware setup. Can be skipped.

### 4.1 Procedure

1. Illuminate the spectrometer with **uniform light** over the full spectral range:
   - Tungsten/halogen lamp (broad spectrum)
   - LED panel with diffuser
   - Clear sky at twilight (avoid direct sun)
2. Ensure **no saturation**: check that no pixels reach 255 (Y8) or 1023 (Y10). Use lower gain or shorter shutter if needed.
3. Capture **10–100 frames** and average them.
4. Save the averaged frame as `flat.npy`.

### 4.2 Avoiding Saturation

- Start with low gain and short shutter
- Inspect histogram: peak should be well below max
- If some pixels saturate, reduce exposure and retake

### 4.3 When to Recalibrate

- After changing optical setup (lens, slit, fibre)
- After changing gain (flat shape can change)
- Periodically if lamp intensity drifts
- Strongly suggested to recalibrate before every measurement series. It takes so little work but ensures best results.

---

## 5. Saving Frames

Frames must be saved as NumPy `.npy` files:

```python
import numpy as np

# After averaging your dark frames
np.save("/path/to/dark.npy", dark_averaged)

# After averaging your flat frames
np.save("/path/to/flat.npy", flat_averaged)
```

Use the `acquire_dark_flat.py` script (see Section 7.3) or a short Python snippet.

---

## 6. Configuring Paths

Add to `spectrometer_config.json` under `processing`:

```json
{
  "processing": {
    "dark_frame_path": "/home/raspberry/spectrometer/calibration/dark.npy",
    "flat_frame_path": "/home/raspberry/spectrometer/calibration/flat.npy",
    "dark_flat_enabled": false,
    "frame_average_n": 1
  }
}
```

- Create the calibration directory if needed: `mkdir -p /home/raspberry/spectrometer/calibration`
- Set `dark_flat_enabled` to `true` via MQTT or config when ready to use.

---

## 7. Acquisition Methods

### 7.1 Webserver UI / REST API

Use this method when `spectrometer_webserver.py` is running.

1. Ensure continuous measurement is stopped.
2. In UI: **Configuration -> Calibration capture -> Dark frame** or **Flat frame**.
3. The backend captures and averages frames, then saves a `.npy` file.
4. Confirm result from response/logs: `path`, `frames_averaged`, and `shape`.

REST endpoints:

- `POST /api/spectrometer/capture_dark_frame`
- `POST /api/spectrometer/capture_flat_frame`

Notes:

- Endpoint returns `409` if continuous acquisition is active.
- API reference: [WEBSERVER_API.md](WEBSERVER_API.md).

### 7.2 MQTT Workflow

There is currently **no dedicated MQTT command** for `capture_dark_frame` or `capture_flat_frame`.

Recommended MQTT-based process:

1. Use camera MQTT topics to set measurement conditions (resolution, shutter, gain, pixel format).
2. Stop RTSP via camera MQTT (`{cmd_topic}rtsp = OFF`).
3. Acquire dark/flat using Webserver method (7.1) or Terminal script (7.3).
4. Enable correction via spectrometer MQTT:
   - `processing_dark_flat_enabled = true`

Topic map: [MQTT_TOPICS.md](MQTT_TOPICS.md).

### 7.3 Terminal Script

Run from the **project root** (parent of `spectrometer/`) so that `spectrometer/` is on the path:

```bash
# Stop RTSP first (publish OFF to rtsp topic), then:
python3 spectrometer/scripts/acquire_dark_flat.py dark 20 /path/to/dark.npy
python3 spectrometer/scripts/acquire_dark_flat.py flat 20 /path/to/flat.npy
```

Or from inside `spectrometer/`:

```bash
python3 scripts/acquire_dark_flat.py dark 20 ./calibration/dark.npy
python3 scripts/acquire_dark_flat.py flat 20 ./calibration/flat.npy
```

Arguments: `(dark|flat)`, `num_frames`, `output_path`. The script captures `num_frames`, averages them, and saves as `.npy`.

---

## 8. Checklist

| Step | Dark | Flat |
|------|------|------|
| Light blocked / uniform | ✓ Block all light | ✓ Uniform illumination |
| Shutter/gain match | ✓ Same as science | ✓ Unsaturated |
| Frames to average | 10–20 | 10–20 |
| Save as .npy | ✓ | ✓ |
| Add paths to config | ✓ | ✓ |
| Enable via MQTT | `processing_dark_flat_enabled` = true | |

---

## 9. Troubleshooting

| Problem | Cause | Fix |
|--------|-------|-----|
| Shape mismatch error | Dark/flat resolution ≠ current capture | Re-acquire with same camera_config resolution |
| Division artifacts | Flat ≈ dark (both low) | Ensure flat has sufficient signal |
| Stripes or bands | Non-uniform illumination | Improve flat uniformity |
| Hot pixels in dark | Normal | Averaging reduces them|
