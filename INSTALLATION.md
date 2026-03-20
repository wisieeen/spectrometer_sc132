# Installation

## 1. Prerequisites

- Raspberry Pi OS (tested on Trixie). See [VERSIONS.md](VERSIONS.md) for dependency versions.
- VEYE MIPI camera with `raspberrypi_v4l2` kernel module and tools
- MQTT broker (e.g. Mosquitto on another machine)
- [mediamtx](https://github.com/bluenviron/mediamtx) for RTSP

### Quick install (recommended)

Run the install script to install dependencies and systemd services:

```bash
chmod +x install/install.sh
./install/install.sh
```

Options: `--no-mediamtx` (mediamtx on another host), `--no-spectrometer`, `--user=USER`. See [install/README.md](install/README.md).

### Manual install

Install system packages:

```bash
sudo apt install -y ffmpeg v4l-utils jq python3 python3-venv python3-full
```
Then create a venv and install packages (or run `install/install.sh` which does this automatically).

## 2. Clone and Configure

Clone this repository (or copy the project files) to your Pi, e.g. `/home/raspberry/`.

### Environment config (required)

Copy the example config and edit with your settings:

```bash
cp env_config.example.json env_config.json
nano env_config.json
```

Fill in:

- **mqtt.broker** – IP or hostname of your MQTT broker
- **mqtt.port** – Usually 1883
- **mqtt.user** / **mqtt.pass** – Broker credentials
- **mqtt.cmd_topic** / **mqtt.state_topic** – Topic prefix (e.g. `lab/monocamera/cmd/`)
- **rtsp.url** – Full RTSP URL where mediamtx receives the stream (e.g. `rtsp://192.168.1.100:8554/mystream`)
- **paths.i2c_tool** – Path to `mv_mipi_i2c_new.sh` (from raspberrypi_v4l2)
- **device.video** – Usually `/dev/video0`
- **device.i2c_bus** – I2C bus number for the camera (often `10`)

**Important:** `env_config.json` contains credentials. Do not commit it to git. It is listed in `.gitignore`.

### Camera config

Create `camera_config.json` if it does not exist:

```json
{
  "resolution": "1080x640",
  "fps": 5,
  "shutter": 4100,
  "gain": 1.0,
  "pixel_format": "Y10"
}
```

`pixel_format`: `Y8` (8-bit), `Y10` or `Y10P` (10-bit). Also settable via MQTT `{cmd_topic}pixel_format` or `{cmd_topic}bit_depth` (8/10).

## 3. mediamtx

Install mediamtx and create a systemd unit. Example unit (`/etc/systemd/system/mediamtx.service`):

```ini
[Unit]
Description=MediaMTX RTSP server
After=network.target

[Service]
ExecStart=/path/to/mediamtx
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

**Do not enable mediamtx at boot.** The MQTT controller starts it when the stream is requested. Disable it:

```bash
sudo systemctl disable mediamtx.service
```

## 4. systemd Services

### rtsp-camera.service

Create `/etc/systemd/system/rtsp-camera.service`:

```ini
[Unit]
Description=RTSP Camera Stream
After=network.target

[Service]
User=raspberry
ExecStart=/bin/bash /home/raspberry/start_rtsp.sh
Restart=always

[Install]
WantedBy=multi-user.target
```

### mqtt-camera.service

Create `/etc/systemd/system/mqtt-camera.service`:

```ini
[Unit]
Description=MQTT Camera Controller
After=network.target

[Service]
User=raspberry
ExecStart=/home/raspberry/spectrometer-sc132/venv/bin/python /home/raspberry/mqtt_camera_control.py
Restart=always

[Install]
WantedBy=multi-user.target
```

### Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable mqtt-camera.service
sudo systemctl start mqtt-camera.service
```

The RTSP stream starts only when you publish `ON` to the rtsp command topic.

## 5. Permissions

Ensure `start_rtsp.sh` is executable:

```bash
chmod +x /home/raspberry/start_rtsp.sh
```

The `raspberry` user must be able to run `sudo systemctl start/stop/restart` for `mediamtx` and `rtsp-camera`, and `sudo shutdown` without a password. Add to sudoers:

```
raspberry ALL=(ALL) NOPASSWD: /bin/systemctl start mediamtx.service, /bin/systemctl stop mediamtx.service, /bin/systemctl start rtsp-camera.service, /bin/systemctl stop rtsp-camera.service, /bin/systemctl restart rtsp-camera.service, /sbin/shutdown
```

## 6. Home Assistant

Add an FFmpeg camera in `configuration.yaml`:

```yaml
stream:

ffmpeg:

camera:
  - platform: ffmpeg
    name: Lab Monocamera
    input: rtsp://YOUR_MEDIAMTX_HOST:8554/mystream
```

Replace `YOUR_MEDIAMTX_HOST` with the host where mediamtx runs.

**Shutdown**: Publish `ON` to `lab/monocamera/cmd/shutdown` (or your `cmd_topic` + `shutdown`) to safely power off the device. The MQTT controller stops the RTSP stream first, then runs `shutdown -h now`. Requires `sudo` permission for `/sbin/shutdown` (see Permissions section).

**Reboot**: Publish `ON` to `lab/monocamera/cmd/reboot` (or your `cmd_topic` + `reboot`) to safely reboot the device. The MQTT controller stops the RTSP stream first, then runs `shutdown -r now`. Uses the same `sudo` permission as shutdown (see Permissions section).

Example MQTT entities for control:

```yaml
mqtt:
  switch:   
    - name: "Lab Mono Camera"
      command_topic: "lab/monocamera/cmd/rtsp"
      payload_on: "ON"
      payload_off: "OFF"

  button:
    - name: "Lab Mono Camera Shutdown"
      command_topic: "lab/monocamera/cmd/shutdown"
      payload_press: "ON"

    - name: "Lab Mono Camera Reboot"
      command_topic: "lab/monocamera/cmd/reboot"
      payload_press: "ON"

  select:
    - name: "Mono Camera Resolution"
      state_topic: "lab/monocamera/state/resolution"
      command_topic: "lab/monocamera/cmd/resolution"
      options:
        - "1080×1080"
        - "1080x640"
        - "1080x320"

  number:     
    - name: "Mono Camera FPS"
      state_topic: "lab/monocamera/state/fps"
      command_topic: "lab/monocamera/cmd/fps"
      min: 1
      max: 120
      step: 1
      mode: slider

    - name: "Mono Camera gain"
      state_topic: "lab/monocamera/state/gain"
      command_topic: "lab/monocamera/cmd/gain"
      min: 1
      max: 16
      step: 1
      mode: slider

    - name: "Mono Camera shutter (µs)"
      unique_id: mono_camera_shutter_us
      state_topic: "lab/monocamera/state/shutter"
      command_topic: "lab/monocamera/cmd/shutter"
      min: 100
      max: 100000
      step: 100
      mode: slider
      
    - name: "Mono Camera shutter long (µs)"
      unique_id: mono_camera_shutterl_us
      state_topic: "lab/monocamera/state/shutter"
      command_topic: "lab/monocamera/cmd/shutter"
      min: 100000
      max: 1000000
      step: 50000
      mode: slider
```
And Dashboard yaml:

```yaml
type: grid
cards:
  - type: heading
    heading: MONOcam
    heading_style: title
  - type: tile
    grid_options:
      rows: 1
      columns: 6
    entity: camera.lab_monocamera
    icon: mdi:video
    show_entity_picture: true
    vertical: false
    features_position: bottom
  - type: entities
    title: Stream Control
    entities:
      - entity: switch.lab_mono_camera
      - entity: select.mono_camera_resolution
      - entity: number.mono_camera_fps
      - entity: button.lab_mono_camera_shutdown
      - entity: button.lab_mono_camera_reboot
    grid_options:
      columns: 18
      rows: auto
  - type: entities
    title: Image Parameters
    entities:
      - entity: number.mono_camera_gain
      - entity: number.mono_camera_shutter_us
      - entity: number.mono_camera_shutterl_us
    grid_options:
      columns: 18
      rows: auto
column_span: 2

```


## 7. Spectrometer (optional)

The spectrometer subproject captures spectra from the same camera. See [spectrometer/README.md](spectrometer/README.md), [spectrometer/docs/USER_GUIDE.md](spectrometer/docs/USER_GUIDE.md), and [spectrometer/docs/INDEX.md](spectrometer/docs/INDEX.md).

**Prerequisites**: RTSP stream must be **OFF** (V4L2 device is exclusive). Stop stream before running spectrometer scripts.

1. Install spectrometer Python deps: run `install/install.sh` (creates venv and installs deps), or manually: `venv/bin/pip install -r spectrometer/requirements.txt`
2. Add `spectrometer` section to `env_config.json` (see `env_config.example.json`)
3. Run `venv/bin/python spectrometer/scripts/spectrometer_service.py` (or add systemd unit via install.sh)
4. Home Assistant integration: see [spectrometer/docs/homeassistant_spectrometer.yaml](spectrometer/docs/homeassistant_spectrometer.yaml)

## 8. Verify

1. Publish `ON` to `lab/monocamera/cmd/rtsp` (or your `cmd_topic` + `rtsp`)
2. Check `sudo systemctl status rtsp-camera.service` and `mediamtx.service`
3. Open the RTSP URL in VLC or Home Assistant

## 9. Troubleshooting

- **Exposure/gain not changing** (MQTT works, `camera_config.json` updates, but image unchanged): See [docs/TROUBLESHOOTING_EXPOSURE_GAIN.md](docs/TROUBLESHOOTING_EXPOSURE_GAIN.md).
- **Webserver: video stream or continuous spectrum won't activate**: See [docs/TROUBLESHOOTING_WEBSERVER_STREAM_SPECTRUM.md](docs/TROUBLESHOOTING_WEBSERVER_STREAM_SPECTRUM.md).
