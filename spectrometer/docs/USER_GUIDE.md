# Spectrometer User Guide

Run scripts from the `spectrometer/` directory. See [INDEX.md](INDEX.md) for all docs.

## Workflow

1. **Preselect camera settings** – resolution, bit depth, framerate, shutter, gain via MQTT or `camera_config.json`.
2. **Start video stream** – publish `ON` to `lab/monocamera/cmd/rtsp`. View in Home Assistant to find spectrum area.
3. **Define acquisition lines** – start point, end point, thickness per channel. Run `spectrometer_calibrate_ui.py` on a machine with display (load preview image via SCP from Pi if needed), or edit `spectrometer_config.json` manually.
4. **Stop stream** – publish `OFF`. Set shutter beyond FPS limit for long exposure (e.g. 500000 µs).
5. **Calibrate** – add [pixel, wavelength] pairs. Use `spectrometer_calibrate_ui.py` (interactive) or `spectrometer_calibrate.py` (CLI). Fit: linear or polynomial.
6. **Measure** – run `spectrometer_service.py`. Publish `start` for continuous, `single` for on-demand, `preview` to capture frame for line placement. Run `spectrum_mqtt_saver.py` on your main device to save spectra as CSV file. Note: copy both `spectrum_mqtt_saver.py`and `spectrum_saver_config.example.json` to your device. 

## Headless Setup

- **Preview**: Run `scripts/spectrometer_preview.py` or publish to `cmd/preview` (when spectrometer_service is running). Saves frame to `/tmp/spectrometer_preview.png`. Fetch via SCP or serve via HTTP.
- **Calibration wizard**: Run `spectrometer_calibrate_ui.py` on a machine with display. Load the preview image (SCP from Pi), define line and calibration points interactively, save config. Copy config back to Pi if needed.
- **Stream for calibration**: Use existing RTSP + Home Assistant FFmpeg camera to view live. Stop stream before measurement.

## Calibration

Use reference lamp (e.g. mercury, sodium). Identify known wavelengths at pixel positions.

**Calibration wizard** (recommended, run on device with display):

```bash
python3 scripts/spectrometer_calibrate_ui.py --image /path/to/spectrometer_preview.png --config /path/to/spectrometer_config.json
```

1. Click "Set line", then click two points on the image (start, end).
2. Click "Add calibration point", then click on the spectrum graph at a known wavelength peak.
3. Enter the wavelength (nm) in the text box, press Enter. Repeat for more points.
4. Choose fit (Linear or Polynomial), click "Save config".

**CLI** (alternative):

```bash
python3 scripts/spectrometer_calibrate.py --calibration-id default --add-pair 0 400
python3 scripts/spectrometer_calibrate.py --calibration-id default --add-pair 500 550
python3 scripts/spectrometer_calibrate.py --calibration-id default --add-pair 999 700 --fit polynomial --degree 2
```

## See Also

- [DARK_FLAT_CALIBRATION.md](DARK_FLAT_CALIBRATION.md) – dark and flat frames for signal processing
- [AGENT_FRONTEND.md](AGENT_FRONTEND.md) – MQTT topics and payload schemas

## Troubleshooting

- **"Device busy" / "Failed to open video device"** – Stop RTSP stream first.
- **Stride mismatch** – Y10/Y10P formats may have padding; `camera_capture` uses cv2 which handles common cases.
- **No spectrum** – Check line coordinates are within frame bounds; thickness > 0.
