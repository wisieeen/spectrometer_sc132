# MQTT Topics

MQTT contract for camera control and spectrometer service.

Topic prefixes come from `env_config.json`:

- Camera: `mqtt.cmd_topic`, `mqtt.state_topic`
- Spectrometer: `spectrometer.cmd_topic`, `spectrometer.state_topic`

## Camera Topics

| Topic | Payload | Description |
|-------|---------|-------------|
| `{cmd_topic}rtsp` | `ON` / `OFF` | Start or stop stream |
| `{cmd_topic}resolution` | e.g. `1080x640` | Set resolution (restarts stream) |
| `{cmd_topic}fps` | e.g. `5` | Set FPS (restarts stream) |
| `{cmd_topic}shutter` | microseconds, e.g. `4100` | Manual exposure time |
| `{cmd_topic}gain` | dB, e.g. `1.0` | Manual gain |
| `{cmd_topic}pixel_format` | `Y8`, `Y10`, `Y10P` | Pixel format (restarts stream) |
| `{cmd_topic}bit_depth` | `8` or `10` | Shorthand (`8 -> Y8`, `10 -> Y10`) |
| `{cmd_topic}shutdown` | `ON` | Stop stream, then shutdown |
| `{cmd_topic}reboot` | `ON` | Stop stream, then reboot |

Camera state is published to `{state_topic}{key}`.

## Spectrometer Topics

Service command topics (under `spectrometer.cmd_topic`):

- `start`, `stop`, `continuous`
- `single`
- `interval_ms`
- `preview`
- `processing_frame_average_n`
- `processing_dark_flat_enabled`
- `processing_richardson_lucy_enabled`
- `processing_richardson_lucy_psf_sigma`
- `processing_richardson_lucy_iterations`
- `processing_richardson_lucy_psf_path`

State and data are published under `spectrometer.state_topic` (implementation details in `spectrometer/scripts/spectrometer_service.py` and `spectrometer/docs/AGENT_FRONTEND.md`).
