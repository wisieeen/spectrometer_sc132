# SC132 Spectrometer on Raspberry Pi Zero 2 W

Spectrometer software stack built around the VEYE RAW-MIPI-SC132M sensor and a Raspberry Pi Zero 2 W (typically headless).

## Goal
This project aims to build spectrometer with multiple control channels (webserver, MQTT, REST API).

### This repository contains:

- Spectrometer acquisition + processing (preview, calibration, spectrum extraction, optional dark/flat and Richardson–Lucy)
- Control plane via MQTT (camera control + spectrometer service)
- Optional webserver UI + REST API for remote operation

## Tested Hardware/OS

Only this setup is currently verified:

- Raspberry Pi Zero 2 W
- Raspberry Pi OS (Raspbian) Trixie
- VEYE RAW-MIPI-SC132M with `raspberrypi_v4l2`

Other VEYE cameras may work, but are not validated in this repository.

## What This Project Is

- **Spectrometer workflow** (`spectrometer/`): capture from `/dev/video0`, extract spectra from configured acquisition lines, apply calibration/processing, publish results over MQTT (and optionally via webserver).
- **Camera control + RTSP streaming** (`mqtt_camera_control.py`, `start_rtsp.sh`): set imaging parameters and run an RTSP stream when you need a live view (e.g. alignment/calibration).
- **Boot/runtime automation** (`install/`, GPIO modes, AP/STA handling, service orchestration): install scripts and system integration for unattended use.

Important constraint: the camera device is exclusive. If the RTSP stream is running, spectrometer scripts/services cannot open `/dev/video0` (and vice-versa).

This repository originated from [`SC132M-on-RPi-Zero-2-W-MQTT-control`](https://github.com/wisieeen/SC132M-on-RPi-Zero-2-W-MQTT-control) and evolved into a broader spectrometer system.

## Quick Navigation

- **Docs index (start here)**: [`docs/INDEX.md`](docs/INDEX.md)
- **Get it running**: [`docs/INSTALLATION.md`](docs/INSTALLATION.md)
- **Operator workflow (calibrate + measure)**: [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md)
- **MQTT contract (camera + spectrometer)**: [`docs/MQTT_TOPICS.md`](docs/MQTT_TOPICS.md)
- **Web UI layout**: [`docs/WEBSERVER_UI.md`](docs/WEBSERVER_UI.md)
- **Webserver REST API**: [`docs/WEBSERVER_API.md`](docs/WEBSERVER_API.md)
- **Tested dependency versions**: [`VERSIONS.md`](VERSIONS.md)

## Notes

- Practical SC132M capture modes known to work: `1080x640`, `1080x320`; `1080x1080` may work depending on setup.
- `env_config.json` contains credentials and must stay local (already in `.gitignore`).

## License

GNU GPL 3.0
