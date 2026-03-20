#!/bin/bash
# NetworkManager start hook for spectrometer AP/STA switching.
#
# Idea (first layer): NetworkManager's service must finish starting before we
# reliably switch the Wi-Fi mode. This script is executed via an
# NetworkManager.service drop-in (ExecStartPost).
#
# It checks the bootstrap flag (/run/spectrometer-ap-enabled) and then:
# - brings up the AP connection (`spectrometer-ap`) when flag exists
# - brings down the AP connection when flag does not exist
#
# It is safe to run repeatedly.

set -e

CON_NAME="spectrometer-ap"
AP_FLAG="/run/spectrometer-ap-enabled"
MODE="${1:-full}"

ALLOW_PORTS_COMMENT="spectrometer-ap-allow"

allow_incoming_wlan0() {
  # Allow incoming connections on wlan0 (some NM shared-mode setups reject).
  iptables -C INPUT -i wlan0 -m comment --comment "$ALLOW_PORTS_COMMENT" -j ACCEPT 2>/dev/null || \
    iptables -I INPUT -i wlan0 -m comment --comment "$ALLOW_PORTS_COMMENT" -j ACCEPT 2>/dev/null || true
}

delete_allow_incoming_wlan0() {
  iptables -D INPUT -i wlan0 -m comment --comment "$ALLOW_PORTS_COMMENT" -j ACCEPT 2>/dev/null || true
}

active_conn_on_wlan0() {
  nmcli -t -f GENERAL.CONNECTION device show wlan0 2>/dev/null | head -n1 | cut -d: -f2-
}

if [ "$MODE" = "full" ]; then
  if [ -f "$AP_FLAG" ]; then
    # Reload connection files so NM sees the written .nmconnection.
    nmcli con reload 2>/dev/null || true
    nmcli con up "$CON_NAME" 2>/dev/null || true
  fi
fi

# Firewall + AP teardown: use both active connection and AP_FLAG so STA mode
# never leaves INPUT ACCEPT on wlan0 while a stale spectrometer-ap is up.
active="$(active_conn_on_wlan0)"
if [ "$active" = "$CON_NAME" ]; then
  if [ -f "$AP_FLAG" ]; then
    allow_incoming_wlan0
  else
    if [ "$MODE" = "full" ]; then
      nmcli con down "$CON_NAME" 2>/dev/null || true
    fi
    delete_allow_incoming_wlan0
  fi
else
  if [ "$MODE" = "full" ] && [ ! -f "$AP_FLAG" ]; then
    nmcli con down "$CON_NAME" 2>/dev/null || true
  fi
  delete_allow_incoming_wlan0
fi

