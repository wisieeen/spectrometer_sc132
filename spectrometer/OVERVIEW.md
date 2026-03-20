# Spectrometer Module Overview

Camera-as-sensor spectrometer module for Raspberry Pi.

It captures frames from `/dev/video0`, extracts intensity profiles from configured acquisition lines, applies calibration and optional processing, and publishes spectra via MQTT.

## Critical Runtime Rule

`/dev/video0` is exclusive: RTSP streaming must be off before spectrometer capture.

## Quick Workflow

1. Stop RTSP stream (`{cmd_topic}rtsp -> OFF`).
2. Configure camera settings (`camera_config.json` or MQTT).
3. Run preview: `python3 scripts/spectrometer_preview.py`.
4. Calibrate via `scripts/spectrometer_calibrate_ui.py` (or `spectrometer_calibrate.py`).
5. Run service: `python3 scripts/spectrometer_service.py`.

## Main Scripts

| Script | Purpose |
|--------|---------|
| `scripts/camera_capture.py` | V4L2 capture and frame handling |
| `scripts/spectrometer_preview.py` | Save preview frame for line placement |
| `scripts/spectrometer_calibrate.py` | CLI calibration |
| `scripts/spectrometer_calibrate_ui.py` | Interactive calibration UI |
| `scripts/acquire_dark_flat.py` | Dark/flat acquisition |
| `scripts/spectrometer_service.py` | MQTT-controlled spectrometer service |
| `scripts/spectrometer_webserver.py` | Flask webserver and REST API |

## MQTT Commands (spectrometer service)

Prefix comes from `env_config.json -> spectrometer.cmd_topic`.

- `start`, `stop`, `continuous`
- `single`
- `interval_ms`
- `preview`
- `processing_*` controls (frame averaging, dark/flat, Richardson-Lucy settings)

## Configuration Files

- `spectrometer_config.json` (or `spectrometer_config.example.json`)
- shared `env_config.json` (`spectrometer` section)
- shared `camera_config.json`

## More Documentation

- [docs/INDEX.md](docs/INDEX.md) - full spectrometer docs map
- [docs/USER_GUIDE.md](docs/USER_GUIDE.md) - operator workflow
- [docs/AGENT_FRONTEND.md](docs/AGENT_FRONTEND.md) - integration contract
