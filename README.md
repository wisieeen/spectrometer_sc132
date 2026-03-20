# SC132 Spectrometer on Raspberry Pi Zero 2 W

Spectrometer software stack built around VEYE RAW-MIPI-SC132M and Raspberry Pi Zero 2 W.  
The project provides calibration tooling, spectrum extraction, MQTT control, and optional RTSP/webserver interfaces for remote operation.

## Tested Hardware/OS

Only this setup is currently verified:

- Raspberry Pi Zero 2 W
- Raspberry Pi OS (Raspbian) Trixie
- VEYE RAW-MIPI-SC132M with `raspberrypi_v4l2`

Other VEYE cameras may work, but are not validated in this repository.

## What This Project Is

- Spectrometer-first workflow (`spectrometer/`): preview, calibration, acquisition, processing, MQTT publishing
- Camera control layer (`mqtt_camera_control.py`, `start_rtsp.sh`) used to set imaging parameters and stream when needed
- Boot/runtime automation (`install/`, GPIO modes, AP/STA handling, service orchestration)

This repository originated from [`SC132M-on-RPi-Zero-2-W-MQTT-control`](https://github.com/wisieeen/SC132M-on-RPi-Zero-2-W-MQTT-control) and evolved into a broader spectrometer system.

## Quick Navigation

- [INSTALLATION.md](INSTALLATION.md) - installation and deployment
- [spectrometer/OVERVIEW.md](spectrometer/OVERVIEW.md) - spectrometer workflow and scripts
- [docs/MQTT_TOPICS.md](docs/MQTT_TOPICS.md) - camera and spectrometer MQTT contract
- [docs/INDEX.md](docs/INDEX.md) - full documentation index
- [VERSIONS.md](VERSIONS.md) - tested dependency versions

## Notes

- Practical SC132M capture modes known to work: `1080x640`, `1080x320`; `1080x1080` may work depending on setup.
- `env_config.json` contains credentials and must stay local (already in `.gitignore`).

## License

GNU GPL 3.0
