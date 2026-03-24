# AP Mode and WiFi Credentials: Diagnostic Plan

## Root Cause Analysis (from research)

### 1. Why WiFi credentials don't change (STA mode)

**On Bookworm/Trixie:** NetworkManager manages WiFi. The system **ignores** `/etc/wpa_supplicant/wpa_supplicant.conf` for normal NM operation. Our flow:

- Webserver writes credentials
- **`apply_wifi_credentials.sh`** uses `nmcli device wifi connect` when NetworkManager is active

### 2. Why AP mode doesn't work (historical)

Single-radio conflict: only one mode on `wlan0` at a time. Competing managers (legacy hostapd vs NM) caused flapping. **Current fix:** one NM connection profile for AP + ordered hook + dispatcher limited to firewall sync.

### 3. Log file visibility

The **boot partition** (FAT32) is visible when the SD card is mounted on Windows. Log to `/boot/firmware/spectrometer-bootstrap.log` (or `/boot/` on older Pi OS).

---

## Diagnostic Log Contents (bootstrap)

Each boot appends lines like:

```
=== ISO datetime ===
mode: {wifi_mode, webserver, mqtt}
skip_network: true|false
network_config: ap|sta
NetworkManager_active: true|false
ap_nmconnection_exists: true|false
ap_autoconnect: true|false   # if file exists
wlan0_addrs: [...]
errors: [...]
```

After WiFi save (from webserver), `apply_wifi_credentials.sh` can append a save result block (see script).

---

## Implementation (done)

1. **Bootstrap logging** – appends to boot partition log.
2. **apply_wifi_credentials** – `nmcli` when NetworkManager is active.
3. **spectrometer-diagnostics.service** – post-boot state (see `install/diagnostics.sh`).
4. **Webserver** – WiFi config endpoints as documented in webserver docs.
