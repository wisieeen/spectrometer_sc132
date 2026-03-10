# Dependency Versions

Versions used and tested with this project. Update this file when upgrading.

| Component | Version | Notes |
|-----------|---------|-------|
| **Python** | 3.11+ | 3.13.5 tested |
| **paho-mqtt** | 2.1.0+ | `pip install paho-mqtt` |
| **ffmpeg** | 4.4+ | From system packages |
| **v4l2-ctl** | 1.28+ | Part of `v4l-utils` |
| **jq** | 1.6+ | For parsing JSON in shell scripts |
| **mediamtx** | 1.x | See releases on GitHub |
| **Raspberry Pi OS** | Bookworm / Trixie | Debian 12/13 based |

## Python packages

**Camera (mqtt_camera_control):**
```
paho-mqtt>=2.1.0
```

**Spectrometer** (see `spectrometer/requirements.txt`):
```
numpy>=1.20.0
opencv-python-headless>=4.5.0
matplotlib>=3.5.0
paho-mqtt>=1.6.0
```

Install camera: `pip install paho-mqtt`  
Install spectrometer: `pip install -r spectrometer/requirements.txt`

## System packages (Debian / Raspberry Pi OS)

```bash
sudo apt install ffmpeg v4l-utils jq python3-paho-mqtt
```

## External projects

- **raspberrypi_v4l2** – VEYE MIPI camera driver and tools. Although official wiki claims that mvcam-raspberrypi repo is the correct one, it wasn't the case for me (with RAW-MIPI-SC132M camera). Provides `mv_mipi_i2c_new.sh`, `i2c_4read`, `i2c_4write` and drivers.

## Verifying versions

```bash
python3 --version
python3 -c "import paho.mqtt.client; print('paho-mqtt', paho.mqtt.client.__version__)"
ffmpeg -version | head -1
v4l2-ctl --version
jq --version
mediamtx --version
```
