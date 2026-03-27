# Install Scripts

Reference for `install/install.sh` and related boot/network helpers.

## install.sh

Installs dependencies, creates venv, deploys systemd units, and configures sudoers.

Usage:

```bash
cd /path/to/spectrometer-sc132
chmod +x install/install.sh
./install/install.sh
```

Options:

- `--no-mediamtx` - skip mediamtx install
- `--user=USER` - install services for a specific user

What it installs/configures:

1. System packages (`ffmpeg`, `v4l-utils`, `jq`, `python3`, `python3-venv`, `python3-full`)
2. Python venv at `venv/` with `paho-mqtt`, `RPi.GPIO`, and `spectrometer/requirements.txt`
3. mediamtx binary/service (installed but disabled at boot; started on demand)
4. `raspberrypi_v4l2` tools/driver on Raspberry Pi
5. systemd services:
   - `spectrometer-bootstrap`
   - `spectrometer-network-recovery`
   - `spectrometer-diagnostics`
   - `spectrometer-apply-wifi-credentials`
   - `mqtt-camera`
   - `rtsp-camera`
   - `mediamtx` (RTSP infrastructure)
   - `spectrometer` (MQTT mode)
   - `spectrometer-webserver` (webserver mode)
6. sudoers rules for camera control and safe power actions

## Related docs

- [../INSTALLATION.md](../INSTALLATION.md) - full install procedure
- [../docs/GPIO_MODES.md](../docs/GPIO_MODES.md) - GPIO behavior and mode flags
- [../docs/NETWORK_RECOVERY.md](../docs/NETWORK_RECOVERY.md) - boot trigger recovery
- [../docs/AP_WIFI_DIAGNOSTIC_PLAN.md](../docs/AP_WIFI_DIAGNOSTIC_PLAN.md) - diagnostics
