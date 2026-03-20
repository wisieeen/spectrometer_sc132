#!/bin/bash
# Manual AP mode recovery - use when bootstrap AP fails and wpa_supplicant holds wlan0.
# NOTE: AP may disappear after ~20s if dhcpcd starts wpa_supplicant. For a persistent fix,
# run install/install.sh to deploy bootstrap with dhcpcd nohook + systemd drop-in, then reboot.

sudo systemctl stop wpa_supplicant@wlan0.service 2>/dev/null
sudo systemctl mask wpa_supplicant@wlan0.service 2>/dev/null
# Remove any DHCP-assigned addresses
for addr in $(ip -4 addr show wlan0 | grep -oP 'inet \K[\d.]+/[\d]+'); do
  [ "$addr" != "192.168.4.1/24" ] && sudo ip addr del "$addr" dev wlan0 2>/dev/null || true
done
sudo ip link set wlan0 down
sudo systemctl restart hostapd
sudo ip addr add 192.168.4.1/24 dev wlan0 2>/dev/null || sudo ip addr replace 192.168.4.1/24 dev wlan0
sudo ip link set wlan0 up
sudo systemctl restart dnsmasq
echo "AP should appear. If it disappears, deploy bootstrap fix and reboot."
