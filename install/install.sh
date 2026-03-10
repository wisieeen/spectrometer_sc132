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
echo "[1/6] Installing system packages..."
sudo apt update
sudo apt install -y ffmpeg v4l-utils jq python3-pip python3-venv

# paho-mqtt: prefer pip for newer version (VERSIONS.md: 2.1.0+)
# python3-paho-mqtt is often older; pip gives control
sudo apt install -y python3-paho-mqtt 2>/dev/null || true

# --- 2. Python packages ---
echo "[2/6] Installing Python packages..."
pip3 install --user --break-system-packages paho-mqtt 2>/dev/null || pip3 install --user paho-mqtt

if [ "$SPECTROMETER_INSTALL" = true ]; then
  pip3 install --user --break-system-packages -r "$PROJECT_DIR/spectrometer/requirements.txt" 2>/dev/null || \
  pip3 install --user -r "$PROJECT_DIR/spectrometer/requirements.txt"
fi

# --- 3. mediamtx (optional) ---
if [ "$MEDIAMTX_INSTALL" = true ]; then
  echo "[3/6] Installing mediamtx..."
  MEDIAMTX_VERSION="v1.16.3"
  ARCH=$(uname -m)
  case "$ARCH" in
    aarch64|arm64)  MEDIAMTX_ARCH="arm64" ;;
    armv7l|armhf)   MEDIAMTX_ARCH="armv7" ;;
    x86_64)         MEDIAMTX_ARCH="amd64" ;;
    *)              echo "Unsupported arch: $ARCH"; exit 1 ;;
  esac
  MEDIAMTX_TAR="mediamtx_${MEDIAMTX_VERSION#v}_linux_${MEDIAMTX_ARCH}.tar.gz"
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
  echo "[3/6] Skipping mediamtx (--no-mediamtx)"
fi

# --- 4. Config check ---
echo "[4/6] Checking config..."
if [ ! -f "$PROJECT_DIR/env_config.json" ]; then
  echo "  WARNING: env_config.json not found. Copy from env_config.example.json and edit:"
  echo "    cp $PROJECT_DIR/env_config.example.json $PROJECT_DIR/env_config.json"
  echo "    nano $PROJECT_DIR/env_config.json"
fi
if [ ! -f "$PROJECT_DIR/camera_config.json" ]; then
  echo "  WARNING: camera_config.json not found. Create it (see INSTALLATION.md)."
fi

# --- 5. systemd units ---
echo "[5/6] Installing systemd services..."

# Update paths in env_config paths.home if different
HOME_DIR=$(eval echo ~$INSTALL_USER)

# mqtt-camera.service
sudo tee /etc/systemd/system/mqtt-camera.service > /dev/null << EOF
[Unit]
Description=MQTT Camera Controller
After=network.target

[Service]
User=$INSTALL_USER
Environment=ENV_CONFIG=$PROJECT_DIR/env_config.json
ExecStart=/usr/bin/python3 $PROJECT_DIR/mqtt_camera_control.py
WorkingDirectory=$PROJECT_DIR
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# rtsp-camera.service
chmod +x "$PROJECT_DIR/start_rtsp.sh"
sudo tee /etc/systemd/system/rtsp-camera.service > /dev/null << EOF
[Unit]
Description=RTSP Camera Stream
After=network.target

[Service]
User=$INSTALL_USER
Environment=ENV_CONFIG=$PROJECT_DIR/env_config.json
ExecStart=/bin/bash $PROJECT_DIR/start_rtsp.sh
WorkingDirectory=$PROJECT_DIR
Restart=always

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

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl disable mediamtx.service 2>/dev/null || true
  echo "  mediamtx.service: installed, disabled at boot (MQTT starts on demand)"
fi

# spectrometer.service (optional)
if [ "$SPECTROMETER_INSTALL" = true ]; then
  sudo tee /etc/systemd/system/spectrometer.service > /dev/null << EOF
[Unit]
Description=Spectrometer Service
After=network.target

[Service]
User=$INSTALL_USER
Environment=ENV_CONFIG=$PROJECT_DIR/env_config.json
ExecStart=/usr/bin/python3 $PROJECT_DIR/spectrometer/scripts/spectrometer_service.py
WorkingDirectory=$PROJECT_DIR
Restart=always

[Install]
WantedBy=multi-user.target
EOF
  echo "  spectrometer.service: installed (enable manually if needed)"
fi

sudo systemctl daemon-reload
sudo systemctl enable mqtt-camera.service
sudo systemctl enable rtsp-camera.service
echo "  mqtt-camera.service, rtsp-camera.service: enabled at boot"

# --- 6. Sudoers ---
echo "[6/6] Configuring sudoers..."
SUDOERS_FILE="/etc/sudoers.d/spectrometer-sc132"
sudo tee "$SUDOERS_FILE" > /dev/null << EOF
# Passwordless systemctl for MQTT camera control (start/stop mediamtx, rtsp-camera, shutdown)
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
echo "Optional: enable spectrometer at boot:"
echo "  sudo systemctl enable spectrometer.service"
echo "  sudo systemctl start spectrometer.service"
echo ""
