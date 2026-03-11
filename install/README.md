# Installation Scripts

## install.sh

Installs dependencies and systemd services for the spectrometer-sc132 project.

**Usage:**
```bash
cd /path/to/spectrometer-sc132
chmod +x install/install.sh
./install/install.sh
```

**Options:**
- `--no-mediamtx` – Skip mediamtx install (use when mediamtx runs on another host)
- `--no-spectrometer` – Skip spectrometer Python deps and spectrometer.service
- `--user=USER` – Install for USER (default: current user)

**What it does:**
1. Installs system packages: ffmpeg, v4l-utils, jq, python3-pip, python3-rpi.gpio, hostapd, dnsmasq
2. Installs Python packages: paho-mqtt, spectrometer requirements (incl. flask)
3. Downloads and installs mediamtx (unless `--no-mediamtx`)
4. Downloads and installs raspberrypi_v4l2 driver (Raspberry Pi only; Pi 5 vs other auto-detected). Reboot required after first install.
5. Creates systemd units: spectrometer-bootstrap, mqtt-camera, rtsp-camera, mediamtx, spectrometer, spectrometer-webserver
6. spectrometer-bootstrap runs early (reads GPIO, configures AP/STA); mqtt-camera, rtsp-camera, spectrometer are conditional on GPIO flags; spectrometer is enabled at boot
7. Adds sudoers entry for passwordless systemctl/shutdown

**GPIO bootstrap:** See `docs/GPIO_MODES.md`. Pins 5=WiFi mode, 6=webserver, 7=MQTT.

**Prerequisites:**
- Raspberry Pi OS (Debian-based)
- Run as the user that will own the services (e.g. `raspberry`)

**After install:**
- Edit `env_config.json` and `camera_config.json`
- Start: `sudo systemctl start mqtt-camera.service`

**Uninstall services:**
```bash
sudo systemctl stop mqtt-camera rtsp-camera spectrometer spectrometer-webserver mediamtx spectrometer-bootstrap 2>/dev/null
sudo systemctl disable mqtt-camera rtsp-camera spectrometer spectrometer-webserver spectrometer-bootstrap 2>/dev/null
sudo rm /etc/systemd/system/mqtt-camera.service /etc/systemd/system/rtsp-camera.service
sudo rm /etc/systemd/system/spectrometer-bootstrap.service /etc/systemd/system/spectrometer-webserver.service 2>/dev/null
sudo rm /etc/systemd/system/mediamtx.service /etc/systemd/system/spectrometer.service 2>/dev/null
sudo rm /etc/sudoers.d/spectrometer-sc132
sudo systemctl daemon-reload
```
