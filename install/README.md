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
1. Installs system packages: ffmpeg, v4l-utils, jq, python3-pip
2. Installs Python packages: paho-mqtt, spectrometer requirements
3. Downloads and installs mediamtx (unless `--no-mediamtx`)
4. Creates systemd units: mqtt-camera, rtsp-camera, mediamtx, spectrometer
5. Enables mqtt-camera and rtsp-camera at boot
6. Adds sudoers entry for passwordless systemctl/shutdown

**Prerequisites:**
- Raspberry Pi OS (Debian-based)
- Run as the user that will own the services (e.g. `raspberry`)

**After install:**
- Edit `env_config.json` and `camera_config.json`
- Start: `sudo systemctl start mqtt-camera.service`

**Uninstall services:**
```bash
sudo systemctl stop mqtt-camera rtsp-camera spectrometer mediamtx 2>/dev/null
sudo systemctl disable mqtt-camera rtsp-camera spectrometer 2>/dev/null
sudo rm /etc/systemd/system/mqtt-camera.service /etc/systemd/system/rtsp-camera.service
sudo rm /etc/systemd/system/mediamtx.service /etc/systemd/system/spectrometer.service 2>/dev/null
sudo rm /etc/sudoers.d/spectrometer-sc132
sudo systemctl daemon-reload
```
