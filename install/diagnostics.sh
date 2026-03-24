#!/bin/bash
# Append post-boot diagnostics to boot partition log (visible when SD card read on PC).
LOG="/boot/firmware/spectrometer-bootstrap.log"
[ -d /boot/firmware ] || LOG="/boot/spectrometer-bootstrap.log"
[ -d /boot ] || exit 0

{
  echo "=== post-boot $(date -Iseconds) ==="
  echo "NetworkManager: $(systemctl is-active NetworkManager 2>/dev/null || echo '?')"
  echo "nm_wlan0: $(nmcli -t -f GENERAL.STATE device show wlan0 2>/dev/null | head -1 || echo 'unknown')"
  echo "nm_ap_con: $(nmcli -t -f NAME,STATE con show 2>/dev/null | grep spectrometer-ap || echo 'not found')"
  echo "wlan0: $(ip -4 addr show wlan0 2>/dev/null | grep 'inet ' || echo 'no addrs')"
  echo "spectrometer-webserver: $(systemctl is-active spectrometer-webserver 2>/dev/null || echo '?')"
} >> "$LOG" 2>/dev/null || true
