# Spectrometer User Guide

See [INDEX.md](INDEX.md) for all docs.

## Before You Start (applies to all workflows)

- The camera device is exclusive. **Stop RTSP streaming before spectrometer measurement** (otherwise `/dev/video0` is busy).
- Ensure configs exist and are correct:
  - `env_config.json` (MQTT broker + spectrometer topic prefixes)
  - `camera_config.json` (resolution/fps/shutter/gain/pixel format)
  - `spectrometer/spectrometer_config.json` (acquisition lines + wavelength calibration)

## Workflow A: Webserver UI (recommended for day-to-day use)

Use the webserver for calibration capture, parameter control, and spectrum viewing.

1. Open the web UI. Layout reference: [WEBSERVER_UI.md](WEBSERVER_UI.md).
2. (Optional) If you plan to use dark/flat correction, follow [DARK_FLAT_CALIBRATION.md](DARK_FLAT_CALIBRATION.md).
3. In **Configuration → Calibration capture**, trigger **Preview** and use the saved preview image for calibration (line placement + wavelength points).
4. In the **Spectrometer** tab:
   - Start continuous acquisition (Start) or request a single spectrum (Single).
   - Tune processing (frame average, dark/flat, Richardson–Lucy). Notes: [RICHARDSON_LUCY.md](RICHARDSON_LUCY.md).
5. Export/save:
   - Use your frontend/integration to store spectra, or subscribe to MQTT topics (see Workflow B).

REST API reference (if integrating without the UI): [WEBSERVER_API.md](WEBSERVER_API.md).

## Workflow B: MQTT (Home Assistant / automation / headless)

Use MQTT when you want automation, Home Assistant entities, or a headless control plane.

1. Configure `env_config.json`:
   - Camera topic prefixes under `mqtt.*`
   - Spectrometer topic prefixes under `spectrometer.*`
2. Ensure RTSP is **OFF** before measurement (or you will get “device busy”).
3. Start the spectrometer service on the Pi (systemd or manual). Then publish commands under `spectrometer.cmd_topic`:
   - `preview` (capture a preview image for calibration/line placement)
   - `single` (one spectrum)
   - `start` / `stop` (continuous)
   - processing toggles/parameters (frame averaging, dark/flat, Richardson–Lucy)
4. Subscribe to published spectra/state under `spectrometer.state_topic`.

Topic map: [MQTT_TOPICS.md](MQTT_TOPICS.md). Integration payload expectations: [AGENT_FRONTEND.md](AGENT_FRONTEND.md).

## Workflow C: Terminal / SSH (scripts-first)

Run everything from the `spectrometer/` directory on the Pi unless noted otherwise.

1. Stop RTSP streaming (if running).
2. Preview image for calibration/line placement:

```bash
python3 scripts/spectrometer_preview.py
```

This writes `/tmp/spectrometer_preview.png` (copy it to your workstation for calibration UI).
3. Calibration (on a machine with display is easiest):
   - Run the UI calibration tool and save to a config JSON:

```bash
python3 scripts/spectrometer_calibrate_ui.py --image /path/to/spectrometer_preview.png --config /path/to/spectrometer_config.json
```

   - Copy the generated config to the Pi as `spectrometer/spectrometer_config.json`.
4. (Optional) If you plan to use dark/flat correction, follow [DARK_FLAT_CALIBRATION.md](DARK_FLAT_CALIBRATION.md).

5. Measurement:
   - Run the MQTT-controlled service:

```bash
python3 scripts/spectrometer_service.py
```

   - Or use the webserver (also provides REST API + UI):

```bash
python3 scripts/spectrometer_webserver.py
```

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
- [MQTT_TOPICS.md](MQTT_TOPICS.md) – topic map for camera and spectrometer
- [AGENT_FRONTEND.md](AGENT_FRONTEND.md) – integration contract and payload schemas

## Troubleshooting

- **"Device busy" / "Failed to open video device"** – Stop RTSP stream first.
- **Stride mismatch** – Y10/Y10P formats may have padding; `camera_capture` uses cv2 which handles common cases.
- **No spectrum** – Check line coordinates are within frame bounds; thickness > 0.
