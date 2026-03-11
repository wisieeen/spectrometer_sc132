# Spectrometer Documentation Index

Quick reference to all documentation files. Links are relative to this file.

---

## Root Project


| File                                                                 | Description                                         |
| -------------------------------------------------------------------- | --------------------------------------------------- |
| [../../README.md](../../README.md)                                   | Main project: MQTT camera control, RTSP streaming   |
| [../../INSTALLATION.md](../../INSTALLATION.md)                       | Full setup: camera, mediamtx, systemd, spectrometer |
| [../../VERSIONS.md](../../VERSIONS.md)                               | Dependency versions (Python, paho-mqtt, etc.)       |
| [../../raspberrypi_v4l2/README.md](../../raspberrypi_v4l2/README.md) | VEYE MIPI driver build (local & cross-compile)      |
| [../../docs/GPIO_MODES.md](../../docs/GPIO_MODES.md)                 | GPIO pin assignment, boot mode selection             |
| [../../docs/WEBSERVER_API.md](../../docs/WEBSERVER_API.md)           | Webserver REST API spec                              |
| [../../docs/WEBSERVER_UI.md](../../docs/WEBSERVER_UI.md)              | Webserver interface layout, themes                   |


---

## Spectrometer Docs (this folder)

### User & Setup


| File                                                 | Description                                                     |
| ---------------------------------------------------- | --------------------------------------------------------------- |
| [USER_GUIDE.md](USER_GUIDE.md)                       | Step-by-step workflow: calibration, measurement, headless setup |
| [DARK_FLAT_CALIBRATION.md](DARK_FLAT_CALIBRATION.md) | Acquiring dark and flat frames for signal processing            |


### Integration


| File                                                               | Description                                                                                |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| [AGENT_FRONTEND.md](AGENT_FRONTEND.md)                             | MQTT contract, schemas for Home Assistant / TypeScript frontend                            |
| [homeassistant_spectrometer.yaml](homeassistant_spectrometer.yaml) | Home Assistant MQTT config, template switch, dashboard (see also `../for_home_assistant/`) |


### Implementation


| File                                                           | Description                                                   |
| -------------------------------------------------------------- | ------------------------------------------------------------- |
| [CODER_INSTRUCTIONS.md](CODER_INSTRUCTIONS.md)                 | Tech stack, constraints, checklist, optical tools             |
| [SIGNAL_PROCESSING_RESEARCH.md](SIGNAL_PROCESSING_RESEARCH.md) | Research: deconvolution, dark/flat, frame avg, baseline, etc. |


### Optical Design


| File                                                                   | Description                                                                                                        |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| [OPTICAL_EQUATIONS.md](OPTICAL_EQUATIONS.md)                           | Grating equation, collimation, resolution formulas                                                                 |
| [SPECTROMETER_ML_OPTIMIZATION.md](SPECTROMETER_ML_OPTIMIZATION.md)     | ML techniques for geometry optimization (Bayesian, genetic)                                                        |
| [spectrometer_optical_simulator.py](spectrometer_optical_simulator.py) | Interactive ray diagram (run from `docs/`, needs matplotlib)                                                       |
| [spectrometer_ml_optimizer.py](spectrometer_ml_optimizer.py)           | Geometry optimizer (run: `python spectrometer_ml_optimizer.py --method both`, needs `requirements-optical-ml.txt`) |


---

## Related Links

- **Spectrometer config**: `spectrometer_config.json`, `spectrometer_config.example.json`
- **Home Assistant split config**: [../for_home_assistant/](../for_home_assistant/) – `copy_to_configuration.yaml`, `copy_to_dashboard.yaml` (alternative to `homeassistant_spectrometer.yaml`)
- **Spectrum chart**: [spectrum-card.js](spectrum-card.js) (copy to HA `www/`, add as Lovelace resource)

