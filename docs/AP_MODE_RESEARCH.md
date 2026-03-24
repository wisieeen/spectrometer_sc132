# AP Mode Research: Why AP Reverts to STA

> **Current install (Bookworm):** AP is a NetworkManager Wi‑Fi profile (`spectrometer-ap.nmconnection`), not hostapd. Bootstrap + `nm_ap_sta_hook.sh` (NM `ExecStartPost`) + dispatcher `90-spectrometer-ap` (`firewall-only`) implement switching. Sections below remain useful background on single-radio conflicts.

## Summary of User Reports

Other Raspberry Pi users report similar issues:

1. **AP appears then disappears** – hostapd runs, SSID shows briefly, then wlan0 reverts to STA and reconnects to a saved network.
2. **Single-radio conflict** – wlan0 can be either AP or STA, not both. Any service that tries to connect wlan0 as a client will take over from hostapd.
3. **Multiple actors can take over wlan0** – not just wpa_supplicant; dhcpcd hooks and **NetworkManager** can also manage wlan0 and reconnect to saved networks.

---

## Root cause: Raspberry Pi OS Bookworm uses NetworkManager

**Raspberry Pi OS 12 (Bookworm)** uses **NetworkManager** as the default WiFi manager instead of wpa_supplicant directly. This affects both Lite and Desktop.

| Pi OS version | Network stack | Notes |
|---------------|---------------|-------|
| Bullseye and earlier | wpa_supplicant + dhcpcd | Our fixes (mask, dhcpcd nohook) target this |
| **Bookworm and later** | **NetworkManager** | NetworkManager manages WiFi; wpa_supplicant runs under it |

**Implication:** On Bookworm, NetworkManager can still manage wlan0 even when wpa_supplicant is masked. It can:

- Reconnect to saved networks in `/etc/NetworkManager/system-connections/`
- Take over wlan0 when hostapd is running
- Cause the AP to disappear after ~20 seconds

---

## Solutions Reported by Others

### 1. Tell NetworkManager to not manage wlan0 (when in AP mode)

Create `/etc/NetworkManager/conf.d/99-spectrometer-ap.conf`:

```ini
[device-wlan0-unmanaged]
match-device=interface-name:wlan0
managed=0
```

Then restart NetworkManager and reboot. When switching back to STA mode, remove this file so NetworkManager can manage wlan0 again.

### 2. Use NetworkManager for AP instead of hostapd

Use NetworkManager’s built-in hotspot instead of hostapd/dnsmasq:

```bash
sudo nmcli connection add type wifi ifname wlan0 con-name spectrometer-ap ssid spectrometer mode ap
sudo nmcli connection modify spectrometer-ap 802-11-wireless.band bg
sudo nmcli connection modify spectrometer-ap 802-11-wireless.channel 6
sudo nmcli connection modify spectrometer-ap wifi-sec.key-mgmt wpa-psk
sudo nmcli connection modify spectrometer-ap wifi-sec.psk "yourpassword"
sudo nmcli connection modify spectrometer-ap ipv4.addresses 192.168.4.1/24
sudo nmcli connection modify spectrometer-ap ipv4.method shared
sudo nmcli connection up spectrometer-ap
```

This avoids hostapd vs NetworkManager conflicts by using NetworkManager for both AP and STA.

### 3. Use dhcpcd `nohook wpa_supplicant` (legacy stack)

On systems that still use dhcpcd/wpa_supplicant (pre-Bookworm or custom):

```ini
# In /etc/dhcpcd.conf
interface wlan0
nohook wpa_supplicant
```

### 4. Use a separate USB WiFi adapter

For AP + STA at the same time, use a second USB WiFi adapter for one of the modes. This avoids single-interface conflicts.

---

## Why It Cannot Be Solved Reliably

On single-interface setups:

1. **Multiple managers** – wpa_supplicant, dhcpcd hooks, and NetworkManager can all try to manage wlan0.
2. **Boot order** – Services start in different orders; the “winner” depends on timing.
3. **Reconnection** – NetworkManager and wpa_supplicant are designed to reconnect to saved networks automatically.
4. **OS version** – Pi OS Bookworm’s NetworkManager changes the rules; old hostapd/dhcpcd guides no longer apply.

---

## Recommended Approach

**1. Check which stack is active on your Pi:**

```bash
systemctl is-active NetworkManager
systemctl is-active wpa_supplicant@wlan0
ls /etc/NetworkManager/system-connections/
```

**2. If NetworkManager is active:**

- **Option A:** Add the unmanage config for wlan0 when in AP mode (bootstrap creates it; removes it when switching to STA).
- **Option B:** Switch from hostapd to NetworkManager hotspot mode.

**3. If you are on Bullseye or older:**

- Use dhcpcd `nohook wpa_supplicant` and the wpa_supplicant systemd drop-in.
- Ensure hostapd starts after wlan0 is ready.

---

## Implemented Fix (this repo)

- Bootstrap writes `/etc/NetworkManager/system-connections/spectrometer-ap.nmconnection` (AP) or sets `autoconnect=false` and removes `/run/spectrometer-ap-enabled` (STA).
- `spectrometer-nm-ap-sta-hook.sh` runs after NetworkManager starts (`ExecStartPost`) to `reload` / `con up` the AP when the flag exists, and applies/removes the iptables INPUT rule on `wlan0`.
- Dispatcher `90-spectrometer-ap` calls the hook with `firewall-only` so link events do not repeatedly `nmcli con up/down` (which caused ~10s disconnect loops).
