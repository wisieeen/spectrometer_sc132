# AP Mode: Research Summary and Solution

## Problem History

Multiple boot attempts with hostapd showed consistent failures:
- hostapd remained `inactive` (never started)
- No journal entries for hostapd
- SSID sometimes visible but clients couldn't connect
- dnsmasq inactive, wlan0 had no IP

## Root Causes Found

### 1. systemd boot transaction (hostapd never starts)

**Source**: [systemd/systemd#23034](https://github.com/systemd/systemd/issues/23034)

systemd builds its full dependency tree at boot start. When the bootstrap service (running early at `Before=network.target`) calls `systemctl enable hostapd`, the boot transaction has already been planned. New dependencies are not picked up mid-boot. hostapd was never included in the boot plan.

### 2. DAEMON_CONF not set

`/etc/default/hostapd` had `DAEMON_CONF` commented out. Even if hostapd started, it wouldn't know which config file to use.

### 3. hostapd masked by Pi OS

Raspberry Pi OS Bookworm with NetworkManager masks hostapd by default.

### 4. WPA2 cipher mismatch

`wpa_pairwise=TKIP` + `rsn_pairwise=CCMP` caused connection failures with some clients.

### 5. Missing country_code

Without `country_code` in hostapd.conf, some drivers fail to create the AP properly.

## Solution: Switch to NetworkManager (nmcli)

On Raspberry Pi OS Bookworm, **NetworkManager is the recommended way to create AP hotspots**:

**Sources**:
- [RaspberryTips: Access Point (Bookworm Ready)](https://raspberrytips.com/access-point-setup-raspberry-pi)
- [Step-by-step nmcli hotspot 2025](https://information-architects.de/944854-2/)
- [Raspberry Pi Forums: AP with NetworkManager](https://forums.raspberrypi.com/viewtopic.php?t=357998)

### Advantages over hostapd

- Works *with* NetworkManager instead of fighting it
- No hostapd, dnsmasq, dhcpcd, wpa_supplicant conflicts
- `ipv4.method=shared` provides built-in DHCP + NAT
- No systemd boot transaction issues (NM reads connection files at startup)
- Single `.nmconnection` file replaces 5+ config files and 3 systemd services

### How it works

1. Bootstrap writes `/etc/NetworkManager/system-connections/spectrometer-ap.nmconnection` with `autoconnect=true` (AP mode) or `autoconnect=false` (STA mode)
2. Bootstrap runs before NM starts, so the file is ready when NM reads it
3. NM activates the AP connection, assigns 192.168.4.1/24, starts DHCP server
4. No hostapd, dnsmasq, spectrometer-ap-ip, or spectrometer-unmask-hostapd needed
