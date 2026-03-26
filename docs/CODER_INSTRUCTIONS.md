# Coder Instructions

Concise implementation notes for spectrometer subproject. See [INDEX.md](INDEX.md) for all docs.

## Tech Stack

- **Python**: Project uses venv at `$PROJECT_DIR/venv`. Run scripts with `venv/bin/python` or `./venv/bin/python`. Install creates venv; systemd services use venv Python.
- **Camera**: cv2.VideoCapture(device, cv2.CAP_V4L2) — force V4L2 backend (GStreamer fails with MV camera). v4l2-ctl, I2C tool (from raspberrypi_v4l2)
- **Image**: OpenCV, numpy. Format: GREY/Y8 (Y10/Y10P supported). Stride handled in camera_capture via v4l2-ctl bytes-per-line; crop when stride_width != width (see start_rtsp.sh).
- **Output**: paho-mqtt. Modular: `OutputAdapter` in `lib/output/`

## Critical Constraints

1. **V4L2 exclusive**: rtsp-camera must be stopped before any spectrometer script uses `/dev/video0`.
2. **Shutter**: In `camera_capture`, do NOT clamp shutter to FPS. Streaming does; single-frame capture allows long exposure.
3. **Headless**: No cv2.imshow. Preview saves frame to file; user defines lines via config or MQTT.
4. **Stride**: When driver reports bytes-per-line > width, crop frame to logical width. All capture must go through `camera_capture.capture_frame()` which handles this.

## Implementation Checklist

- [x] `lib/config.py` – load/save spectrometer_config, read paths from env_config
- [x] `lib/spectrum.py` – extract_line_profile, fit_calibration, compute_spectrum
- [x] `scripts/camera_capture.py` – ensure stream stopped, configure device, capture frame, stride crop (v4l2-ctl bytes-per-line)
- [x] `scripts/spectrometer_preview.py` – capture + save to file
- [x] `lib/output/base.py` + `mqtt_adapter.py`
- [x] `scripts/spectrometer_calibrate.py` – CLI for pairs, fit, coefficients
- [x] `scripts/spectrometer_calibrate_ui.py` – interactive wizard: line selection, spectrum, calibration, save config (device with display)
- [x] `scripts/spectrometer_service.py` – MQTT loop, capture, extract, publish (commands: start, stop, single, interval_ms, preview, processing_*)
- [x] `lib/signal_processing/` – dark_flat, richardson_lucy; each technique independent, MQTT-toggleable
- [x] `scripts/spectrometer_webserver.py` – Flask REST API + web UI; runs spectrometer when webserver GPIO enabled
- [x] `install/gpio_bootstrap.py` – GPIO read at boot, mode/flag files, network AP/STA config

## Line Extraction Algorithm

For line (x1,y1)→(x2,y2), thickness t: sample N points along line; at each point sum pixels in strip of width t perpendicular; return 1D intensity array. Use `numpy`; consider `scipy.ndimage.map_coordinates` for robustness.

## Signal Processing (lib/signal_processing/)

Each technique is independent. Toggle via MQTT: `cmd/processing_frame_average_n`, `cmd/processing_dark_flat_enabled`, `cmd/processing_richardson_lucy_enabled`. Config: `spectrometer_config.json` → `processing`. Dark/flat calibration: see `docs/DARK_FLAT_CALIBRATION.md`. Richardson–Lucy: see `docs/RICHARDSON_LUCY.md`.

## env_config Paths

Reuse `paths.camera_config`, `paths.i2c_tool`, `device.video`, `device.i2c_bus`, `services.*`. Add `spectrometer.cmd_topic`, `spectrometer.state_topic`, `spectrometer.config_path` (optional). Add `gpio`, `wifi`, `webserver` for GPIO bootstrap and webserver.

## Optical Path Tools

- **../../helper_scripts/OPTICAL_EQUATIONS.md** - Grating equation, collimation, resolution formulas.
- **../../helper_scripts/spectrometer_optical_simulator.py** - Interactive ray diagram. Requires matplotlib.
