# Installation Scripts

## install.sh

Installs dependencies and systemd services for the spectrometer-sc132 project.

**Usage:**
```bash
cd /path/to/spectrometer-sc132
chmod +x install/install.sh
./install/install.sh
```

> **Note:** Run with `bash` or `./install.sh` (honors shebang). Do not use `sh install.sh` — it causes "Bad substitution" because the script uses bash-specific syntax.

**Options:**
- `--no-mediamtx` – Skip mediamtx install (use when mediamtx runs on another host)
- `--no-spectrometer` – Skip spectrometer Python deps and spectrometer.service
- `--user=USER` – Install for USER (default: current user)

**What it does:**
1. Installs system packages: ffmpeg, v4l-utils, jq, python3, python3-venv, python3-full
2. Creates virtual environment at `$PROJECT_DIR/venv` and installs Python packages (paho-mqtt, RPi.GPIO, spectrometer requirements incl. flask)
3. Downloads and installs mediamtx (unless `--no-mediamtx`)
4. Downloads and installs raspberrypi_v4l2 driver (Raspberry Pi only; Pi 5 vs other auto-detected). Reboot required after first install.
5. Creates systemd units: spectrometer-bootstrap, mqtt-camera, rtsp-camera, mediamtx, spectrometer, spectrometer-webserver
6. spectrometer-bootstrap runs early (reads GPIO, configures AP/STA via NetworkManager); mqtt-camera, rtsp-camera, spectrometer are conditional on GPIO flags; spectrometer is enabled at boot
7. Adds sudoers entry for passwordless systemctl/shutdown

**GPIO bootstrap:** See `docs/GPIO_MODES.md`. Pins 5=WiFi mode, 6=webserver, 7=MQTT.

**AP mode:** Uses NetworkManager (nmcli) on Bookworm. Set WiFi country once: `sudo raspi-config nonint do_wifi_country US` (or your country). AP settings (SSID, passphrase, channel) are in `env_config.json` under `wifi`.

**WiFi credentials:** When saving via webserver in STA mode, `apply_wifi_credentials.sh` applies credentials with `nmcli` (when NetworkManager is active), marks that profile as preferred autoconnect, and demotes other STA profiles to prevent reconnecting to an older network after reboot. Sudoers allows the install user to run this script.

**Prerequisites:**
- Raspberry Pi OS (Debian-based)
- Run as the user that will own the services (e.g. `raspberry`)

**After install:**
- Edit `env_config.json` and `camera_config.json`
- Start: `sudo systemctl start mqtt-camera.service`

**Running scripts manually:** Use the venv Python, e.g. `./venv/bin/python spectrometer/scripts/spectrometer_service.py` or `./venv/bin/python install/gpio_bootstrap.py`

**Network recovery:** If the Pi cannot connect (no STA, no AP), place an empty file `spectrometer-network-recovery` in the boot partition and reboot. See `docs/NETWORK_RECOVERY.md`.

**Diagnostics:** Each boot appends to `spectrometer-bootstrap.log` in the boot partition. Read the SD card on another PC to inspect GPIO mode, service states, and errors. See `docs/AP_WIFI_DIAGNOSTIC_PLAN.md`.

**Uninstall services:**
```bash
sudo systemctl stop mqtt-camera rtsp-camera spectrometer spectrometer-webserver mediamtx spectrometer-bootstrap 2>/dev/null
sudo systemctl disable mqtt-camera rtsp-camera spectrometer spectrometer-webserver spectrometer-bootstrap spectrometer-network-recovery spectrometer-diagnostics 2>/dev/null
sudo rm /etc/systemd/system/mqtt-camera.service /etc/systemd/system/rtsp-camera.service
sudo rm /etc/systemd/system/spectrometer-bootstrap.service /etc/systemd/system/spectrometer-webserver.service /etc/systemd/system/spectrometer-network-recovery.service /etc/systemd/system/spectrometer-diagnostics.service 2>/dev/null
sudo rm -f /etc/NetworkManager/dispatcher.d/90-spectrometer-ap
sudo rm -f /lib/systemd/system/NetworkManager.service.d/10-spectrometer-ap-sta.conf
sudo rm -f /usr/local/bin/spectrometer-nm-ap-sta-hook.sh
sudo rm -f /etc/systemd/system/spectrometer-unmask-hostapd.service /etc/systemd/system/spectrometer-ap-ip.service
sudo rm -f /etc/NetworkManager/system-connections/spectrometer-ap.nmconnection
sudo rm /etc/systemd/system/mediamtx.service /etc/systemd/system/spectrometer.service 2>/dev/null
sudo rm /etc/sudoers.d/spectrometer-sc132
sudo systemctl daemon-reload
```
