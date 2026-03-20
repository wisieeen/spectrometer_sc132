# AP Mode and WiFi Credentials: Diagnostic Plan

## Root Cause Analysis (from research)

### 1. Why WiFi credentials don't change (STA mode)

**On Bookworm/Trixie:** NetworkManager manages WiFi. The system **ignores** `/etc/wpa_supplicant/wpa_supplicant.conf`. Our flow:
- Webserver writes to `wifi_credentials.conf` (wpa_supplicant format)
- `apply_wifi_credentials.sh` copies to wpa_supplicant.conf and restarts wpa_supplicant
- **No effect** – NetworkManager uses its own connections in `/etc/NetworkManager/system-connections/`

**Fix:** Use `nmcli device wifi connect SSID password PASS` when NetworkManager is active. This creates/updates the connection in NetworkManager.

### 2. Why AP mode doesn't work

Possible causes (need diagnostics to confirm):
- **NetworkManager unmanage** – wlan0 unmanaged, but hostapd may fail for other reasons
- **Boot order** – hostapd starts before wlan0 is ready
- **Driver/firmware** – brcmf (Pi WiFi) may have quirks
- **Conflicting services** – something still takes wlan0 after our config
- **spectrometer-ap-ip timing** – IP assignment may fail or be too late

### 3. Log file visibility

The **boot partition** (FAT32) is visible when the SD card is mounted on Windows. Log to `/boot/firmware/spectrometer-bootstrap.log` (or `/boot/` on older Pi OS). The file will appear in the boot drive root when you read the SD card on another computer.

---

## Diagnostic Log Contents

Each boot appends to the log:

```
=== YYYY-MM-DD HH:MM:SS ===
mode: {wifi_mode, webserver, mqtt}
gpio_raw: (wifi_ap, webserver, mqtt)  # from read_gpio_pins
recovery_trigger: yes|no
skip_network: yes|no
network_config: ap|sta
NetworkManager_active: yes|no
wpa_supplicant_masked: yes|no
hostapd_status: active|inactive|failed
hostapd_masked: yes|no
wlan0_addrs: [list of IPs]
wlan0_state: UP|DOWN|...
nm_wlan0_managed: yes|no
errors: [any exceptions]
```

After WiFi save (from webserver), append:
```
=== WiFi save YYYY-MM-DD HH:MM:SS ===
ssid: <masked>
method: nmcli|wpa_supplicant
result: success|fail
error: <if any>
```

---

## Implementation (done)

1. **Bootstrap logging** – appends to `/boot/firmware/spectrometer-bootstrap.log` (or `/boot/`). Visible when SD card read on PC.
2. **apply_wifi_credentials** – uses nmcli when NetworkManager is active; else wpa_supplicant copy. Logs result to boot partition.
3. **spectrometer-diagnostics.service** – runs after network-online, appends post-boot state (hostapd, dnsmasq, wlan0 addrs, etc.).
4. **Webserver GET /config/wifi** – now returns current SSID from wifi_credentials.conf for form display.
