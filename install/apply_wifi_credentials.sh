#!/bin/bash
# Apply WiFi credentials: use nmcli (NetworkManager) on Bookworm/Trixie, else wpa_supplicant.
# Called by webserver when user saves WiFi credentials (STA mode only).
# Usage: sudo ./apply_wifi_credentials.sh
# Logs result to boot partition for SD card inspection.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_CONFIG="${ENV_CONFIG:-$PROJECT_DIR/env_config.json}"
LOG="/boot/firmware/spectrometer-bootstrap.log"
[ -d /boot/firmware ] || LOG="/boot/spectrometer-bootstrap.log"

_log() { echo "$1" >> "$LOG" 2>/dev/null || true; }

if [ ! -f "$ENV_CONFIG" ]; then
    _log "=== WiFi save FAIL: env_config not found ==="
    exit 1
fi

HOME_DIR=$(jq -r '.paths.home // "/home/raspberry"' "$ENV_CONFIG")
STA_PATH=$(jq -r '.wifi.sta_config_path // "/etc/wpa_supplicant/wpa_supplicant.conf"' "$ENV_CONFIG")
CREDS="$HOME_DIR/wifi_credentials.conf"

if [ ! -f "$CREDS" ]; then
    _log "=== WiFi save FAIL: wifi_credentials.conf not found ==="
    exit 1
fi

# Do not apply when in AP mode (would start wpa_supplicant and break AP)
if [ -f /run/spectrometer-ap-enabled ]; then
    _log "=== WiFi save: AP mode, credentials saved for next STA boot ==="
    exit 0
fi

# Parse SSID and password from wifi_credentials.conf (simple extraction)
SSID=$(grep 'ssid=' "$CREDS" 2>/dev/null | head -1 | sed 's/.*ssid="\([^"]*\)".*/\1/')
PSK=$(grep 'psk=' "$CREDS" 2>/dev/null | head -1 | sed 's/.*psk="\([^"]*\)".*/\1/')

if [ -z "$SSID" ]; then
    _log "=== WiFi save FAIL: could not parse SSID from wifi_credentials.conf ==="
    exit 1
fi

# On Bookworm/Trixie, NetworkManager manages WiFi - wpa_supplicant.conf is ignored
if systemctl is-active NetworkManager >/dev/null 2>&1; then
    _log "=== WiFi save $(date -Iseconds): using nmcli (NetworkManager) ==="
    if nmcli device wifi connect "$SSID" password "$PSK" 2>/dev/null; then
        _log "WiFi save result: success (nmcli)"
    else
        _log "WiFi save result: FAIL (nmcli) - check SSID/password"
        exit 1
    fi
else
    _log "=== WiFi save $(date -Iseconds): using wpa_supplicant ==="
    cp "$CREDS" "$STA_PATH"
    systemctl restart wpa_supplicant@wlan0.service 2>/dev/null || true
    _log "WiFi save result: copied to $STA_PATH, restarted wpa_supplicant"
fi
