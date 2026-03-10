# RAW-MIPI-SC132M Veye camera MQTT Control for Raspberry Pi Zero 2 W

MQTT-controlled camera streaming for VEYE MIPI cameras (tested on RAW-MIPI-SC132M) on Raspberry Pi. Streams via RTSP through mediamtx, controllable from Home Assistant or any MQTT client.

**Spectrometer subproject**: The `spectrometer/` folder contains a camera-as-spectrometer module that extracts spectra from the same camera. See [spectrometer/README.md](spectrometer/README.md) and [spectrometer/docs/INDEX.md](spectrometer/docs/INDEX.md).

RAW-MIPI-SC132M WARNING: heigth value of 1280px is bugged. For me worked correctly with "1080×1080", "1080x640" and "1080x320", other resolutions were not tested.

## Features

- **MQTT control**: Start/stop stream, set resolution, FPS, exposure, gain, bit depth (pixel format)
- **On-demand streaming**: mediamtx and camera start only when requested (saves power when idle)
- **Live exposure/gain**: Changes apply without restarting the stream
- **Home Assistant**: Integrate via FFmpeg camera platform

## Requirements

- Raspberry Pi (tested on Pi Zero 2W)
- VEYE MIPI camera with `raspberrypi_v4l2` driver
- [mediamtx](https://github.com/bluenviron/mediamtx) (RTSP server)
- MQTT broker (e.g. Mosquitto)
- `ffmpeg`, `v4l2-ctl`, `jq`

## Quick Start

1. Copy the environment config and fill in your values:
   ```bash
   cp env_config.example.json env_config.json
   # Edit env_config.json with your MQTT broker, credentials, RTSP URL
   ```

2. See [INSTALLATION.md](INSTALLATION.md) for full setup (camera + optional spectrometer). See [VERSIONS.md](VERSIONS.md) for dependency versions.

3. Publish `ON` to `lab/monocamera/cmd/rtsp` to start the stream; `OFF` to stop.

## MQTT Topics

| Topic | Payload | Description |
|-------|---------|-------------|
| `{cmd_topic}rtsp` | `ON` / `OFF` | Start or stop stream |
| `{cmd_topic}resolution` | e.g. `1080x640` | Set resolution (restarts stream) |
| `{cmd_topic}fps` | e.g. `5` | Set FPS (restarts stream) |
| `{cmd_topic}shutter` | microseconds, e.g. `4100` | Manual exposure time |
| `{cmd_topic}gain` | dB, e.g. `1.0` | Manual gain |
| `{cmd_topic}pixel_format` | `Y8`, `Y10`, `Y10P` | Bit depth: Y8=8-bit, Y10/Y10P=10-bit (restarts stream) |
| `{cmd_topic}bit_depth` | `8`, `10` | Shorthand for pixel_format (8→Y8, 10→Y10) |

State is published to `{state_topic}{key}` (e.g. `lab/monocamera/state/fps`, `lab/monocamera/state/pixel_format`).

## Configuration

- **env_config.json** – Broker, credentials, paths, device (see `env_config.example.json`)
- **camera_config.json** – Resolution, FPS, shutter, gain, pixel_format (updated by MQTT commands)

## Security

`env_config.json` contains MQTT credentials and must not be committed. It is listed in `.gitignore`. Use `env_config.example.json` as a template: copy it to `env_config.json`, fill in your values, and keep the real file local only.

## License

MIT
