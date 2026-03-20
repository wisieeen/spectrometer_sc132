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
# Also normalize Windows line endings (tr -d '\r') to avoid SSID mismatches.
SSID="$(grep 'ssid=' "$CREDS" 2>/dev/null | head -1 | sed 's/.*ssid="\([^"]*\)".*/\1/' | tr -d '\r' | sed 's/[[:space:]]*$//')"
PSK="$(grep 'psk=' "$CREDS" 2>/dev/null | head -1 | sed 's/.*psk="\([^"]*\)".*/\1/' | tr -d '\r')"

if [ -z "$SSID" ]; then
    _log "=== WiFi save FAIL: could not parse SSID from wifi_credentials.conf ==="
    exit 1
fi

# On Bookworm/Trixie, NetworkManager manages WiFi - wpa_supplicant.conf is ignored
if systemctl is-active NetworkManager >/dev/null 2>&1; then
    _log "=== WiFi save $(date -Iseconds): using nmcli (NetworkManager) ==="
    CON_NAME_STA="spectrometer-sta"

    # Deterministic STA profile:
    # - explicitly set wifi-sec.key-mgmt and wifi-sec.psk
    # - ensure only this profile can autoconnect
    #
    # This avoids failures/edge cases from `nmcli device wifi connect ...`
    # where NM may not create a complete security section.
    EXIST="$(nmcli -t -f NAME connection show "$CON_NAME_STA" 2>/dev/null | head -n1 | tr -d '\r')"
    EXIST_TYPE="$(nmcli -t -f TYPE connection show "$CON_NAME_STA" 2>/dev/null | head -n1 | tr -d '\r')"

    if [ -n "$EXIST" ] && [ "$EXIST_TYPE" != "802-11-wireless" ]; then
        nmcli connection delete "$CON_NAME_STA" 2>&1 | head -n1 | tr -d '\r' >/dev/null 2>&1 || true
        EXIST=""
    fi

    if [ -z "$EXIST" ]; then
        ADD_OUT="$(nmcli connection add type wifi ifname wlan0 con-name "$CON_NAME_STA" \
            ssid "$SSID" \
            wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK" \
            connection.autoconnect yes connection.autoconnect-priority 200 \
            ipv4.method auto ipv6.method ignore 2>&1 || true)"
        _log "WiFi save: created '$CON_NAME_STA' (first line: $(printf '%s' "$ADD_OUT" | head -n1 | tr -d '\r'))"
    else
        MOD_OUT="$(nmcli connection modify "$CON_NAME_STA" \
            ssid "$SSID" \
            wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$PSK" \
            connection.autoconnect yes connection.autoconnect-priority 200 2>&1 || true)"
        _log "WiFi save: updated '$CON_NAME_STA' (first line: $(printf '%s' "$MOD_OUT" | head -n1 | tr -d '\r'))"
    fi

    # Demote other STA profiles so reboot does not jump back to previously used WiFi.
    while IFS=':' read -r NAME TYPE; do
        [ -z "$NAME" ] && continue
        [ "$TYPE" = "802-11-wireless" ] || continue
        [ "$NAME" = "$CON_NAME_STA" ] && continue
        [ "$NAME" = "spectrometer-ap" ] && continue
        nmcli connection modify "$NAME" connection.autoconnect no connection.autoconnect-priority 0 2>&1 | head -n1 >/dev/null 2>&1 || true
    done < <(nmcli -t -f NAME,TYPE connection show 2>/dev/null)

    # Apply immediately (best effort; reboot should be deterministic anyway).
    UP_OUT="$(nmcli connection up "$CON_NAME_STA" 2>&1 || true)"
    _log "WiFi save result: connection up (first line: $(printf '%s' "$UP_OUT" | head -n1 | tr -d '\r'))"

    _log "WiFi save nmcli profiles (name|autoconnect|prio):"
    nmcli -t -f NAME,connection.autoconnect,connection.autoconnect-priority connection show 2>/dev/null | \
      while IFS=':' read -r N AC PR; do
        T="$(nmcli -t -f TYPE connection show "$N" 2>/dev/null | head -n1 | tr -d '\r')"
        [ "$T" = "802-11-wireless" ] || continue
        _log "  $N|$AC|$PR"
      done
else
    _log "=== WiFi save $(date -Iseconds): using wpa_supplicant ==="
    cp "$CREDS" "$STA_PATH"
    systemctl restart wpa_supplicant@wlan0.service 2>/dev/null || true
    _log "WiFi save result: copied to $STA_PATH, restarted wpa_supplicant"
fi
