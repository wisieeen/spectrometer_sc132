# Troubleshooting: AP Mode and Spectrometer Webserver

**Pi not connecting at all (no STA, no AP)?** See `docs/NETWORK_RECOVERY.md` for recovery steps.

When testing AP (Access Point) WiFi mode, you may see:
1. No "spectrometer" WiFi network – device stays in STA mode
2. `spectrometer-webserver.service` not starting despite `/run/spectrometer-webserver-enabled` existing

---

## 1. Webserver Service Not Starting

### Root cause: service is disabled

The install script installs `spectrometer-webserver.service` but **does not enable it**. A disabled service will not start at boot even when its condition is met.

### Fix

```bash
sudo systemctl enable spectrometer-webserver.service
sudo systemctl daemon-reload
sudo systemctl start spectrometer-webserver.service
```

### Verify

```bash
systemctl is-enabled spectrometer-webserver.service   # should show "enabled"
systemctl is-active spectrometer-webserver.service   # should show "active"
```

---

## 2. No AP WiFi Network (Device in STA Mode)

AP mode now uses **NetworkManager (nmcli)** — the recommended approach on Raspberry Pi OS Bookworm. The bootstrap writes an NM connection file (`spectrometer-ap.nmconnection`) with `autoconnect=true` when GPIO 5 is LOW. When NM starts, it activates the AP automatically.

GPIO bootstrap reads pins at boot. **GPIO 5 LOW = AP**, **GPIO 5 HIGH = STA**. If you see STA mode, the bootstrap read GPIO 5 as HIGH.

### Diagnostic steps (run on the Pi)

**A. Check boot mode and flags**

```bash
cat /run/spectrometer-boot-mode.json
ls -la /run/spectrometer-*-enabled
```

- `wifi_mode: "ap"` → bootstrap chose AP; issue is NM or connection file
- `wifi_mode: "sta"` → bootstrap chose STA; GPIO 5 was read as HIGH

**B. If wifi_mode is "sta" – verify GPIO wiring**

| Desired mode | GPIO 5 (BCM) | Wiring |
|--------------|--------------|--------|
| AP           | LOW          | Connect to GND |
| STA          | HIGH         | Leave floating or pull-up (default) |

For AP mode: **GPIO 5 must be connected to GND** before power-on. Internal pull-up keeps it HIGH when unconnected.

**C. If wifi_mode is "ap" but no hotspot – check NM AP connection**

```bash
# Is the connection file present?
ls -la /etc/NetworkManager/system-connections/spectrometer-ap.nmconnection

# Is autoconnect enabled?
grep autoconnect /etc/NetworkManager/system-connections/spectrometer-ap.nmconnection

# What does NM show?
nmcli con show
nmcli con show spectrometer-ap

# Is wlan0 in AP mode?
iw dev wlan0 info
```

**D. Manually activate AP (for testing)**

```bash
sudo nmcli con up spectrometer-ap
```

If this fails, check:
- `nmcli con show spectrometer-ap` for errors
- `journalctl -u NetworkManager -n 50 --no-pager` for NM errors

**E. SSID visible, clients connect, but SSH/webserver times out**

NetworkManager's `ipv4.method=shared` adds iptables rules that block incoming traffic on wlan0. The install creates an NM dispatcher script (`/etc/NetworkManager/dispatcher.d/90-spectrometer-ap`) that runs `iptables -I INPUT -i wlan0 -j ACCEPT` after the AP connection comes up.

Re-run `install/install.sh` and reboot. If still blocked, run manually:
```bash
sudo iptables -I INPUT -i wlan0 -j ACCEPT
```

**F. SSID visible but connection fails**

1. **WiFi country not set** – Run once:
   ```bash
   sudo raspi-config nonint do_wifi_country US   # or your country code
   ```
2. **Channel interference** – Try a different channel in `env_config.json` → `wifi.ap_channel` (1, 6, or 11)
3. **rfkill blocking WiFi** – Run `sudo rfkill unblock wifi` and reboot

**G. WiFi credentials from webserver not applied / RPi does not connect after saving**

The webserver writes to `paths.home/wifi_credentials.conf`. In STA mode, `install/apply_wifi_credentials.sh` applies them via `nmcli`. In AP mode, credentials are saved for the next STA boot.

---

## 3. Legacy hostapd/dnsmasq Issues

If upgrading from an older install that used hostapd/dnsmasq, the bootstrap automatically cleans up legacy artifacts. If you still see issues:

```bash
# Stop and disable legacy services
sudo systemctl stop hostapd dnsmasq
sudo systemctl disable hostapd dnsmasq

# Remove legacy configs
sudo rm -f /etc/NetworkManager/conf.d/99-spectrometer-ap.conf
sudo rm -f /etc/systemd/system/wpa_supplicant@wlan0.service.d/spectrometer-ap.conf
sudo rm -f /etc/systemd/system/spectrometer-unmask-hostapd.service
sudo rm -f /etc/systemd/system/spectrometer-ap-ip.service
sudo systemctl daemon-reload
```

---

## 4. Verify env_config path

The bootstrap reads `ENV_CONFIG` (set in the service). If the path is wrong, defaults are used instead of your settings.

```bash
systemctl cat spectrometer-bootstrap.service | grep ENV_CONFIG
cat /run/spectrometer-boot-mode.json
```

---

## 5. Diagnostics

Each boot appends to `spectrometer-bootstrap.log` in the boot partition. Read the SD card on another PC to inspect:
- GPIO mode, NM status, AP connection state, wlan0 addresses, errors

Post-boot diagnostics are appended by `spectrometer-diagnostics.service`.

---

## 6. Quick Reference

| Check | Command |
|-------|---------|
| Boot mode | `cat /run/spectrometer-boot-mode.json` |
| AP flag | `ls /run/spectrometer-ap-enabled` |
| NM connections | `nmcli con show` |
| AP connection details | `nmcli con show spectrometer-ap` |
| wlan0 state | `iw dev wlan0 info` |
| wlan0 IP | `ip addr show wlan0` |
| NM logs | `journalctl -u NetworkManager -n 50` |
| Bootstrap log | Read `/boot/firmware/spectrometer-bootstrap.log` from SD card on PC |

---

## 7. Full AP Mode Checklist (after install)

1. GPIO 5 connected to GND (AP mode)
2. GPIO 6 connected to GND (webserver enabled)
3. `env_config.json` has correct `wifi.ap_ssid` and `wifi.ap_passphrase`
4. WiFi country set: `sudo raspi-config nonint do_wifi_country US`
5. Reboot → WiFi network visible; clients get DHCP from NM (192.168.4.x)
6. Open `http://192.168.4.1:8080` in browser
