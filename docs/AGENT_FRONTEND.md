# Agent Frontend Integration

Instructions for agents building Home Assistant or TypeScript/React frontend. See [INDEX.md](INDEX.md) for all docs.

## MQTT Topics

| Topic | Payload | Description |
|-------|---------|--------------|
| `lab/spectrometer/cmd/start` | (empty) | Start continuous spectrum publishing |
| `lab/spectrometer/cmd/stop` | (empty) | Stop continuous mode |
| `lab/spectrometer/cmd/continuous` | `ON` / `OFF` | Toggle continuous mode (for MQTT switch) |
| `lab/spectrometer/cmd/single` | (empty) | Request one spectrum |
| `lab/spectrometer/cmd/interval_ms` | e.g. `1000` | Set interval (ms) for continuous mode |
| `lab/spectrometer/cmd/processing_frame_average_n` | e.g. `4` | Number of frames to average (1 = off). Persisted to config. |
| `lab/spectrometer/cmd/processing_dark_flat_enabled` | `true` / `false` | Enable dark/flat correction. Persisted to config. |
| `lab/spectrometer/cmd/processing_richardson_lucy_enabled` | `true` / `false` | Enable Richardson–Lucy deconvolution. Persisted to config. |
| `lab/spectrometer/cmd/processing_richardson_lucy_psf_sigma` | e.g. `3.0` | Richardson–Lucy PSF sigma (fallback). 0.5–20. Persisted. |
| `lab/spectrometer/cmd/processing_richardson_lucy_psf_path` | e.g. `/path/to/psf.npy` | Richardson–Lucy custom PSF path (.npy). Empty = use Gaussian. Persisted. |
| `lab/spectrometer/cmd/processing_richardson_lucy_iterations` | e.g. `15` | Richardson–Lucy iterations. 1–100. Persisted. |
| `lab/spectrometer/cmd/preview` | (empty) | Run spectrometer_preview.py; saves frame to `/tmp/spectrometer_preview.png` |
| `lab/spectrometer/state/spectrum/{channel_id}` | JSON | Full spectrum for channel |
| `lab/spectrometer/state/status` | `idle` / `running` | Service status |
| `lab/spectrometer/state/interval_ms` | e.g. `1000` | Current interval (ms); published on startup and when changed |
| `lab/spectrometer/state/processing_frame_average_n` | e.g. `4` | Current frame average count |
| `lab/spectrometer/state/processing_dark_flat_enabled` | `true` / `false` | Current dark/flat enabled state |
| `lab/spectrometer/state/processing_richardson_lucy_enabled` | `true` / `false` | Current Richardson–Lucy enabled state |
| `lab/spectrometer/state/processing_richardson_lucy_psf_sigma` | e.g. `3.0` | Current Richardson–Lucy PSF sigma |
| `lab/spectrometer/state/processing_richardson_lucy_psf_path` | e.g. `/path/to/psf.npy` | Current Richardson–Lucy custom PSF path |
| `lab/spectrometer/state/processing_richardson_lucy_iterations` | e.g. `15` | Current Richardson–Lucy iterations |

Topics configurable via `env_config.json` → `spectrometer.cmd_topic`, `spectrometer.state_topic`.

## Spectrum Payload Schema

```json
{
  "channel_id": "ch0",
  "timestamp": "2025-03-04T12:00:00.000Z",
  "wavelengths_nm": [400.0, 401.0, ...],
  "intensities": [0.1, 0.2, ...],
  "meta": {
    "shutter_us": 100000,
    "gain_db": 4.0,
    "processing": { "frame_average_n": 4, "dark_flat_applied": true, "richardson_lucy_applied": false }
  }
}
```

## Config Schemas

### spectrometer_config.json

```json
{
  "channels": [
    {
      "id": "ch0",
      "line": { "start": [x1, y1], "end": [x2, y2], "thickness": 5 },
      "calibration_id": "default"
    }
  ],
  "calibrations": [
    {
      "id": "default",
      "pairs": [[pixel, wavelength_nm], ...],
      "fit": "linear" | "polynomial",
      "polynomial_degree": 2,
      "coefficients": [c2, c1, c0]
    }
  ],
    "processing": {
    "frame_average_n": 1,
    "dark_flat_enabled": false,
    "dark_frame_path": "/path/to/dark.npy",
    "flat_frame_path": "/path/to/flat.npy",
    "richardson_lucy_enabled": false,
    "richardson_lucy_psf_sigma": 3.0,
    "richardson_lucy_psf_path": null,
    "richardson_lucy_iterations": 15
  }
}
```

See [DARK_FLAT_CALIBRATION.md](DARK_FLAT_CALIBRATION.md) for acquiring dark and flat frames.

### env_config.json extension

```json
{
  "spectrometer": {
    "cmd_topic": "lab/spectrometer/cmd/",
    "state_topic": "lab/spectrometer/state/",
    "config_path": "/home/raspberry/spectrometer_sc132/spectrometer/spectrometer_config.json"
  }
}
```

## Triggering Preview vs Measurement

- **Preview**: Stop RTSP → run `spectrometer_preview.py` or publish to `cmd/preview` (when spectrometer_service is running) → fetch `/tmp/spectrometer_preview.png` → user defines lines → save to config.
- **Measurement**: Stop RTSP → run `spectrometer_service.py` → MQTT `start` or `single`.

## Camera Settings (bit depth, resolution, etc.)

Camera settings (resolution, fps, shutter, gain, **bit depth**/pixel_format) are in `camera_config.json`, shared with the RTSP stream. Control via **mqtt_camera_control** (root project), not spectrometer MQTT: `{cmd_topic}pixel_format` (Y8/Y10/Y10P) or `{cmd_topic}bit_depth` (8/10).

## Future Protocol Extension

Output layer is modular (`lib/output/`). Add `WebSocketAdapter`, `RestAdapter` implementing `OutputAdapter.send_spectrum(spectrum)`. Service selects adapter via config.
