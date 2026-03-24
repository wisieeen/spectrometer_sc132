# Network Recovery: Pi Not Connecting (STA or AP)

When the Pi does not connect to WiFi and does not show the AP SSID, and you can only access the SD card (e.g. from another PC), use one of these methods.

---

## Method 1: Recovery Trigger File (if install was run)

If you have run `install/install.sh` at least once:

1. **Mount the SD card** on your PC. You will see the boot partition (e.g. `H:\` or `E:\`).
2. **Create an empty file** named `spectrometer-network-recovery` (no extension) in the root of that partition.
   - In Notepad: Save As → choose "All files" → filename `spectrometer-network-recovery` (no .txt).
   - Or in CMD: `echo. > H:\spectrometer-network-recovery`
3. **Safely eject** the SD card and boot the Pi.
4. The recovery service will:
   - Remove the AP nmconnection file (disables AP hotspot)
   - Clean up any legacy hostapd/dnsmasq artifacts
   - Disable spectrometer-bootstrap
   - Reboot
5. After reboot, the Pi should use default network (whatever NM connections exist).
6. **Re-enable bootstrap** when ready: `sudo systemctl enable spectrometer-bootstrap.service`

---

## Method 2: Manual Fix (Linux or WSL)

If the recovery script is not installed, or Method 1 fails:

1. **Mount the root partition** (ext4). On Windows with WSL2:
   ```bash
   # In PowerShell (Admin): attach SD card, find disk number in Disk Management
   wsl --mount \\.\PHYSICALDRIVEn --bare
   # In WSL:
   sudo mkdir -p /mnt/piroot
   sudo mount /dev/sdX2 /mnt/piroot   # usually partition 2 is root
   ```
   Or use a Linux live USB and mount the SD card.

2. **Remove the AP connection file** (prefix with `/mnt/piroot` or your mount point):
   - `etc/NetworkManager/system-connections/spectrometer-ap.nmconnection`

3. **Optional legacy cleanup** (if upgrading from older hostapd install):
   - Remove `etc/NetworkManager/conf.d/99-spectrometer-ap.conf`
   - Remove `etc/systemd/system/wpa_supplicant@wlan0.service.d/spectrometer-ap.conf`
   - In `etc/dhcpcd.conf`: delete from `# spectrometer-bootstrap AP: deny wlan0` through `nohook wpa_supplicant`

4. **Unmount and boot** the Pi.

5. **Optional**: To prevent the bootstrap from re-applying network config on future boots, create an empty file `spectrometer-skip-network` in the boot partition. Remove it when you want GPIO-based AP/STA switching again.

---

## Method 3: Re-flash with Raspberry Pi Imager

If the system is badly broken:

1. Use **Raspberry Pi Imager** (Ctrl+Shift+X for advanced options).
2. Set WiFi SSID and password in the Imager before flashing.
3. Flash a fresh image.
4. Copy the project onto the Pi and run `install/install.sh` again.

---

## Boot vs Root Partition

| Partition | Windows | Contents |
|-----------|---------|----------|
| Boot (FAT32) | Visible as drive letter (e.g. H:\\) | Create trigger files here; **spectrometer-bootstrap.log** (diagnostics) |
| Root (ext4) | Not visible; use WSL/Linux to mount | Config files to fix |

**Log file:** After each boot, diagnostics are appended to `spectrometer-bootstrap.log` in the boot partition root. When you read the SD card on another computer, open this file to see GPIO mode, NM status, wlan0 addresses, and any errors.

---

## Why This Happens

AP mode uses a NetworkManager connection file (`spectrometer-ap.nmconnection`) with `autoconnect=true`. If this persists when switching to STA mode (e.g. bootstrap fails, or GPIO misread), NM may activate the AP instead of connecting to WiFi. The recovery removes this file and restores default behavior.
