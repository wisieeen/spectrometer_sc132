#!/bin/bash
# Installation script: dependencies + systemd services
# Run on Raspberry Pi OS (Debian-based). Usage: ./install.sh [--no-mediamtx] [--no-spectrometer] [--user USER]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_USER="${INSTALL_USER:-$USER}"
MEDIAMTX_INSTALL=true
SPECTROMETER_INSTALL=true

for arg in "$@"; do
  case "$arg" in
    --no-mediamtx)    MEDIAMTX_INSTALL=false ;;
    --no-spectrometer) SPECTROMETER_INSTALL=false ;;
    --user=*)         INSTALL_USER="${arg#*=}" ;;
  esac
done

echo "=== Installation: spectrometer-sc132 ==="
echo "Project dir: $PROJECT_DIR"
echo "User: $INSTALL_USER"
echo "Install mediamtx: $MEDIAMTX_INSTALL"
echo "Install spectrometer service: $SPECTROMETER_INSTALL"
echo ""

# --- 1. System packages ---
echo "[1/7] Installing system packages..."
sudo apt update
sudo apt install -y ffmpeg v4l-utils jq python3-pip python3-venv

# RPi.GPIO for GPIO bootstrap (Raspberry Pi only; harmless on other platforms)
sudo apt install -y python3-rpi.gpio 2>/dev/null || true

# hostapd, dnsmasq for WiFi AP mode (GPIO bootstrap)
sudo apt install -y hostapd dnsmasq 2>/dev/null || true

# paho-mqtt: prefer pip for newer version (VERSIONS.md: 2.1.0+)
# python3-paho-mqtt is often older; pip gives control
sudo apt install -y python3-paho-mqtt 2>/dev/null || true

# --- 2. Python packages ---
echo "[2/7] Installing Python packages..."
pip3 install --user --break-system-packages paho-mqtt 2>/dev/null || pip3 install --user paho-mqtt

if [ "$SPECTROMETER_INSTALL" = true ]; then
  pip3 install --user --break-system-packages -r "$PROJECT_DIR/spectrometer/requirements.txt" 2>/dev/null || \
  pip3 install --user -r "$PROJECT_DIR/spectrometer/requirements.txt"
fi

# --- 3. mediamtx (optional) ---
if [ "$MEDIAMTX_INSTALL" = true ]; then
  echo "[3/7] Installing mediamtx..."
  MEDIAMTX_VERSION="v1.16.3"
  ARCH=$(uname -m)
  case "$ARCH" in
    aarch64|arm64)  MEDIAMTX_ARCH="arm64" ;;
    armv7l|armhf)   MEDIAMTX_ARCH="armv7" ;;
    x86_64)         MEDIAMTX_ARCH="amd64" ;;
    *)              echo "Unsupported arch: $ARCH"; exit 1 ;;
  esac
  MEDIAMTX_TAR="mediamtx_${MEDIAMTX_VERSION}_linux_${MEDIAMTX_ARCH}.tar.gz"
  MEDIAMTX_URL="https://github.com/bluenviron/mediamtx/releases/download/${MEDIAMTX_VERSION}/${MEDIAMTX_TAR}"
  MEDIAMTX_DEST="/usr/local/bin/mediamtx"
  MEDIAMTX_CFG="/usr/local/etc/mediamtx.yml"

  if [ -x "$MEDIAMTX_DEST" ]; then
    echo "  mediamtx already installed at $MEDIAMTX_DEST"
  else
    TMP=$(mktemp -d)
    (cd "$TMP" && curl -sL -O "$MEDIAMTX_URL" && tar xzf "$MEDIAMTX_TAR")
    sudo mkdir -p /usr/local/bin /usr/local/etc
    sudo mv "$TMP/mediamtx" "$MEDIAMTX_DEST"
    sudo chmod +x "$MEDIAMTX_DEST"
    if [ -f "$TMP/mediamtx.yml" ]; then
      sudo cp "$TMP/mediamtx.yml" "$MEDIAMTX_CFG"
    fi
    rm -rf "$TMP"
    echo "  mediamtx installed to $MEDIAMTX_DEST"
  fi
else
  echo "[3/7] Skipping mediamtx (--no-mediamtx)"
fi

# --- 4. raspberrypi_v4l2 driver (Raspberry Pi only) ---
ARCH=$(uname -m)
if [[ "$ARCH" == arm* || "$ARCH" == aarch64 ]]; then
  # 4a. Enable I2C (required for camera exposure/gain control)
  CONFIG_FILE=""
  if [ -f /boot/firmware/config.txt ]; then
    CONFIG_FILE="/boot/firmware/config.txt"
  elif [ -f /boot/config.txt ]; then
    CONFIG_FILE="/boot/config.txt"
  fi
  if [ -n "$CONFIG_FILE" ]; then
    for param in "dtparam=i2c_vc=on" "dtparam=i2c_arm=on"; do
      if ! grep -q "^[[:space:]]*${param}" "$CONFIG_FILE" 2>/dev/null; then
        echo "[4/7] Enabling I2C: adding $param to $CONFIG_FILE"
        echo "$param" | sudo tee -a "$CONFIG_FILE" > /dev/null
      fi
    done
    sudo modprobe i2c-dev 2>/dev/null || true
    sudo usermod -aG i2c "$INSTALL_USER" 2>/dev/null || true
  fi

  V4L2_TOOL="$PROJECT_DIR/raspberrypi_v4l2/mv_tools_rpi/mv_mipi_i2c_new.sh"
  if [ -x "$V4L2_TOOL" ]; then
    echo "[4/7] raspberrypi_v4l2 already present at $PROJECT_DIR/raspberrypi_v4l2"
  else
    echo "[4/7] Installing raspberrypi_v4l2 driver..."
    V4L2_URL="https://github.com/veyeimaging/raspberrypi_v4l2/releases/latest/download/raspberrypi_v4l2.tgz"
    TMP_V4L2=$(mktemp -d)
    (cd "$TMP_V4L2" && curl -sL -o raspberrypi_v4l2.tgz "$V4L2_URL" && tar -xzvf raspberrypi_v4l2.tgz)
    if [ -d "$TMP_V4L2/raspberrypi_v4l2" ]; then
      rm -rf "$PROJECT_DIR/raspberrypi_v4l2"
      mv "$TMP_V4L2/raspberrypi_v4l2" "$PROJECT_DIR/"
      cd "$PROJECT_DIR/raspberrypi_v4l2/release"
      chmod +x *
      if [ -f /proc/device-tree/model ]; then
        MODEL=$(cat /proc/device-tree/model 2>/dev/null | tr -d '\0')
        if echo "$MODEL" | grep -q "Pi 5"; then
          echo y | sudo ./install_driver_rpi5.sh veye_mvcam
        else
          echo y | sudo ./install_driver.sh veye_mvcam
        fi
      else
        echo y | sudo ./install_driver.sh veye_mvcam
      fi
      cd "$PROJECT_DIR"
      echo "  raspberrypi_v4l2 installed. Reboot required for driver to load."
    else
      echo "  WARNING: raspberrypi_v4l2 extraction failed (unexpected archive structure)"
    fi
    rm -rf "$TMP_V4L2"
  fi

  # 4b. mv_tools_rpi: chmod +x and compile I2C binaries if needed
  MV_TOOLS="$PROJECT_DIR/raspberrypi_v4l2/mv_tools_rpi"
  if [ -d "$MV_TOOLS" ]; then
    for f in mv_mipi_i2c_new.sh mv_mipi_i2c.sh mv_probe.sh vbyone_i2c_init.sh enable_i2c_vc.sh camera_i2c_config; do
      [ -f "$MV_TOOLS/$f" ] && chmod +x "$MV_TOOLS/$f"
    done
    for f in i2c_4read i2c_4write; do
      [ -f "$MV_TOOLS/$f" ] && chmod +x "$MV_TOOLS/$f"
    done
    if [ ! -x "$MV_TOOLS/i2c_4read" ] && [ -f "$MV_TOOLS/sources/make.sh" ]; then
      echo "  Compiling mv_tools I2C binaries (i2c_4read, i2c_4write)..."
      sudo apt install -y build-essential 2>/dev/null || true
      chmod +x "$MV_TOOLS/sources/make.sh"
      (cd "$MV_TOOLS/sources" && ./make.sh)
      for f in i2c_4read i2c_4write; do
        [ -f "$MV_TOOLS/$f" ] && chmod +x "$MV_TOOLS/$f"
      done
    fi
  fi
else
  echo "[4/7] Skipping raspberrypi_v4l2 (not Raspberry Pi)"
fi

# --- 5. Config check ---
echo "[5/7] Checking config..."
if [ ! -f "$PROJECT_DIR/env_config.json" ]; then
  echo "  WARNING: env_config.json not found. Copy from env_config.example.json and edit:"
  echo "    cp $PROJECT_DIR/env_config.example.json $PROJECT_DIR/env_config.json"
  echo "    nano $PROJECT_DIR/env_config.json"
fi
if [ ! -f "$PROJECT_DIR/camera_config.json" ]; then
  echo "  WARNING: camera_config.json not found. Create it (see INSTALLATION.md)."
fi
if [ -x "$PROJECT_DIR/raspberrypi_v4l2/mv_tools_rpi/mv_mipi_i2c_new.sh" ]; then
  echo "  Set paths.i2c_tool to: $PROJECT_DIR/raspberrypi_v4l2/mv_tools_rpi/mv_mipi_i2c_new.sh"
fi

# --- 6. systemd units ---
echo "[6/7] Installing systemd services..."

# Update paths in env_config paths.home if different
HOME_DIR=$(eval echo ~$INSTALL_USER)

# spectrometer-bootstrap.service (runs early, reads GPIO, creates mode/flag files)
chmod +x "$PROJECT_DIR/install/gpio_bootstrap.py"
sudo tee /etc/systemd/system/spectrometer-bootstrap.service > /dev/null << EOF
[Unit]
Description=Spectrometer GPIO Bootstrap
DefaultDependencies=false
After=sysinit.target local-fs.target
Before=network.target

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 $PROJECT_DIR/install/gpio_bootstrap.py
WorkingDirectory=$PROJECT_DIR
Environment=ENV_CONFIG=$PROJECT_DIR/env_config.json

[Install]
WantedBy=sysinit.target
EOF
sudo systemctl enable spectrometer-bootstrap.service
echo "  spectrometer-bootstrap.service: installed, enabled at boot"

# mqtt-camera.service (conditional on MQTT GPIO)
sudo tee /etc/systemd/system/mqtt-camera.service > /dev/null << EOF
[Unit]
Description=MQTT Camera Controller
After=network.target spectrometer-bootstrap.service
ConditionPathExists=/run/spectrometer-mqtt-enabled

[Service]
User=$INSTALL_USER
Environment=ENV_CONFIG=$PROJECT_DIR/env_config.json
ExecStart=/usr/bin/python3 $PROJECT_DIR/mqtt_camera_control.py
WorkingDirectory=$PROJECT_DIR
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# rtsp-camera.service (conditional on MQTT GPIO) 
chmod +x "$PROJECT_DIR/start_rtsp.sh"
sudo tee /etc/systemd/system/rtsp-camera.service > /dev/null << EOF
[Unit]
Description=RTSP Camera Stream
After=network.target spectrometer-bootstrap.service
ConditionPathExists=/run/spectrometer-mqtt-enabled

[Service]
User=$INSTALL_USER
Environment=ENV_CONFIG=$PROJECT_DIR/env_config.json
ExecStart=/bin/bash $PROJECT_DIR/start_rtsp.sh
WorkingDirectory=$PROJECT_DIR
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# mediamtx.service (installed but NOT enabled at boot - MQTT controller starts it on demand)
if [ "$MEDIAMTX_INSTALL" = true ]; then
  sudo tee /etc/systemd/system/mediamtx.service > /dev/null << EOF
[Unit]
Description=MediaMTX RTSP server
After=network.target

[Service]
ExecStart=/usr/local/bin/mediamtx /usr/local/etc/mediamtx.yml
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl disable mediamtx.service 2>/dev/null || true
  echo "  mediamtx.service: installed, disabled at boot (MQTT starts on demand)"
fi

# spectrometer.service (optional; only when MQTT on AND webserver off - webserver runs spectrometer when enabled)
if [ "$SPECTROMETER_INSTALL" = true ]; then
  sudo tee /etc/systemd/system/spectrometer.service > /dev/null << EOF
[Unit]
Description=Spectrometer Service
After=network.target spectrometer-bootstrap.service
ConditionPathExists=/run/spectrometer-mqtt-enabled
ConditionPathExists=!/run/spectrometer-webserver-enabled

[Service]
User=$INSTALL_USER
Environment=ENV_CONFIG=$PROJECT_DIR/env_config.json
ExecStart=/usr/bin/python3 $PROJECT_DIR/spectrometer/scripts/spectrometer_service.py
WorkingDirectory=$PROJECT_DIR
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl enable spectrometer.service
  echo "  spectrometer.service: installed, enabled at boot"
fi

# spectrometer-webserver.service (conditional on webserver GPIO)
if [ "$SPECTROMETER_INSTALL" = true ]; then
  sudo tee /etc/systemd/system/spectrometer-webserver.service > /dev/null << EOF
[Unit]
Description=Spectrometer Webserver
After=network.target spectrometer-bootstrap.service
ConditionPathExists=/run/spectrometer-webserver-enabled

[Service]
User=$INSTALL_USER
Environment=ENV_CONFIG=$PROJECT_DIR/env_config.json
ExecStart=/usr/bin/python3 $PROJECT_DIR/spectrometer/scripts/spectrometer_webserver.py
WorkingDirectory=$PROJECT_DIR
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  echo "  spectrometer-webserver.service: installed (enable manually if needed)"
fi

sudo systemctl daemon-reload
sudo systemctl enable mqtt-camera.service
sudo systemctl enable rtsp-camera.service
echo "  mqtt-camera.service, rtsp-camera.service: enabled at boot"

# --- 7. Sudoers ---
echo "[7/7] Configuring sudoers..."
SUDOERS_FILE="/etc/sudoers.d/spectrometer-sc132"
sudo tee "$SUDOERS_FILE" > /dev/null << EOF
# Passwordless systemctl for MQTT camera control (start/stop mediamtx, rtsp-camera, shutdown, reboot)
$INSTALL_USER ALL=(ALL) NOPASSWD: /bin/systemctl start mediamtx.service, /bin/systemctl stop mediamtx.service, /bin/systemctl start rtsp-camera.service, /bin/systemctl stop rtsp-camera.service, /bin/systemctl restart rtsp-camera.service, /sbin/shutdown
EOF
sudo chmod 440 "$SUDOERS_FILE"
echo "  Sudoers: $SUDOERS_FILE"

# --- Update env_config paths.home ---
if [ -f "$PROJECT_DIR/env_config.json" ]; then
  # Ensure paths.home matches; user can edit manually
  echo ""
  echo "Ensure env_config.json paths.home is: $PROJECT_DIR (or $HOME_DIR if you use that as project root)"
fi

echo ""
echo "=== Installation complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit env_config.json (MQTT broker, RTSP URL, paths)"
echo "  2. Create camera_config.json if missing"
echo "  3. Start: sudo systemctl start mqtt-camera.service"
echo "  4. Publish ON to cmd_topic/rtsp to start stream"
echo ""
echo "Spectrometer service is enabled at boot (starts when MQTT mode, not webserver)."
echo "If raspberrypi_v4l2 was installed or I2C was enabled, reboot for changes to take effect."
echo ""
