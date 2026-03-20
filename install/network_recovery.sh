#!/bin/bash
# Network recovery: removes spectrometer network overrides when trigger file exists in boot partition.
# Usage: Place empty file "spectrometer-network-recovery" in boot partition (e.g. H:\ on Windows),
#        then boot the Pi. Recovery runs, restores default network config, disables bootstrap, reboots.
#        After reboot, Pi uses default network. Re-enable bootstrap: sudo systemctl enable spectrometer-bootstrap.service

set -e
BOOT_FW="/boot/firmware"
BOOT_ALT="/boot"
TRIGGER="spectrometer-network-recovery"

for boot in "$BOOT_FW" "$BOOT_ALT"; do
  if [ -f "$boot/$TRIGGER" ]; then
    echo "spectrometer-network-recovery: trigger found, restoring default network config"
    rm -f "$boot/$TRIGGER"

    # Remove nmcli AP connection (Bookworm nmcli approach)
    rm -f /etc/NetworkManager/system-connections/spectrometer-ap.nmconnection
    nmcli con reload 2>/dev/null || true

    # Remove NetworkManager start hook (prevents AP/STA switching during recovery)
    rm -f /lib/systemd/system/NetworkManager.service.d/10-spectrometer-ap-sta.conf 2>/dev/null || true
    systemctl daemon-reload 2>/dev/null || true

    # Remove NM dispatcher allow script
    rm -f /etc/NetworkManager/dispatcher.d/90-spectrometer-ap 2>/dev/null || true

    # Clean up legacy hostapd/dnsmasq approach artifacts if present
    rm -f /etc/NetworkManager/conf.d/99-spectrometer-ap.conf
    rm -f /etc/systemd/system/wpa_supplicant@wlan0.service.d/spectrometer-ap.conf
    rmdir /etc/systemd/system/wpa_supplicant@wlan0.service.d 2>/dev/null || true
    if [ -f /etc/dhcpcd.conf ]; then
      sed -i '/# spectrometer-bootstrap AP: deny wlan0/,/nohook wpa_supplicant/d' /etc/dhcpcd.conf
    fi
    systemctl unmask wpa_supplicant@wlan0.service 2>/dev/null || true
    systemctl reload NetworkManager 2>/dev/null || true

    # Disable bootstrap so it doesn't overwrite on next boot
    systemctl disable spectrometer-bootstrap.service 2>/dev/null || true
    systemctl daemon-reload

    echo "Recovery complete. Rebooting in 5s..."
    sleep 5
    reboot
    exit 0
  fi
done
exit 0
