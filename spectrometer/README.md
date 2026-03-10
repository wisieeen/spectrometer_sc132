# Spectrometer Subproject

Camera-as-sensor spectrometer for Raspberry Pi Zero 2 W. Captures images from `/dev/video0`, extracts spectra from user-defined acquisition lines, applies pixel-to-wavelength calibration, publishes via MQTT (modular output).

**Critical**: Spectrum acquisition requires the RTSP stream to be **OFF** (V4L2 device is exclusive). Use existing MQTT camera control to start/stop stream for calibration preview.

## Quick Start

Run from the `spectrometer/` directory (or project root with `spectrometer/` in path).

1. Stop RTSP stream (publish `OFF` to `lab/monocamera/cmd/rtsp`).
2. Set camera settings via MQTT (resolution, shutter, gain) or `camera_config.json`.
3. Run `python3 scripts/spectrometer_preview.py` → saves frame to `/tmp/spectrometer_preview.png` for line placement.
4. Run `python3 scripts/spectrometer_calibrate_ui.py` on a machine with display (SCP image from Pi if needed) to define line, add calibration points, and save config. Or edit `spectrometer_config.json` manually and use `scripts/spectrometer_calibrate.py`.
5. Run `python3 scripts/spectrometer_service.py` → MQTT commands: `start`, `stop`, `single`, `interval_ms`, `preview`.

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/camera_capture.py` | Capture frame from /dev/video0 (stream must be off) |
| `scripts/spectrometer_preview.py` | Save preview frame for remote line definition |
| `scripts/spectrometer_calibrate.py` | Add calibration pairs, set fit, compute coefficients |
| `scripts/spectrometer_calibrate_ui.py` | Interactive wizard: line selection, spectrum, calibration, save config (run on device with display) |
| `scripts/spectrometer_service.py` | Capture loop, extract spectra, publish via MQTT |
| `scripts/acquire_dark_flat.py` | Acquire dark or flat frames for calibration |

## Config

- `spectrometer_config.json` – channels, lines, calibrations (see `spectrometer_config.example.json`)
- `env_config.json` – add optional `spectrometer` section for cmd/state topics
- `camera_config.json` – shared with camera stream (resolution, shutter, gain)

## Dependencies

```bash
pip install -r requirements.txt
```

## Docs

- [docs/INDEX.md](docs/INDEX.md) – documentation index
- [USER_GUIDE.md](docs/USER_GUIDE.md) – step-by-step workflow
- [AGENT_FRONTEND.md](docs/AGENT_FRONTEND.md) – MQTT contract, schemas for Home Assistant / TypeScript frontend
- [DARK_FLAT_CALIBRATION.md](docs/DARK_FLAT_CALIBRATION.md) – Acquiring dark and flat frames for signal processing
- [CODER_INSTRUCTIONS.md](docs/CODER_INSTRUCTIONS.md) – implementation notes, tech stack, optical tools
- [SIGNAL_PROCESSING_RESEARCH.md](docs/SIGNAL_PROCESSING_RESEARCH.md) – signal processing techniques (deconvolution, baseline, etc.)
- [OPTICAL_EQUATIONS.md](docs/OPTICAL_EQUATIONS.md) – grating equation, collimation, resolution
- [SPECTROMETER_ML_OPTIMIZATION.md](docs/SPECTROMETER_ML_OPTIMIZATION.md) – ML geometry optimization
- [homeassistant_spectrometer.yaml](docs/homeassistant_spectrometer.yaml) – Home Assistant MQTT config and dashboard
