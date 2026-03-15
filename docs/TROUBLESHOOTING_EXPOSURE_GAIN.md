# Troubleshooting: Exposure and Gain Not Changing

When MQTT messages reach the device and `camera_config.json` is updated, but exposure/gain do not change visually, the failure is in the **I2C apply step** — not in MQTT or config save.

## Data flow

```
MQTT (shutter/gain) → mqtt_camera_control.py → save_config() → apply_exposure_and_gain()
                                                                    ↓
                                              mv_mipi_i2c_new.sh → i2c_4write → camera sensor
```

## 1. Enable debug logging

In `env_config.json` set `"debug": true`. Restart mqtt-camera:

```bash
sudo systemctl restart mqtt-camera.service
journalctl -u mqtt-camera.service -f
```

Send an MQTT shutter/gain command and watch for:

- `[mqtt_camera] I2C tool not executable at ...` → tool missing or wrong path
- `[mqtt_camera] Applying exposure/gain via I2C: ...` → tool ran (check step 3 if still no effect)
- `[mqtt_camera] Error while applying exposure/gain via I2C` → exception during subprocess

## 2. Verify I2C tool path

`env_config.json` → `paths.i2c_tool` must point to the script on this SD card. Typical values:

- Cloned to `/home/raspberry/spectrometer_sc132/`:  
  `"/home/raspberry/spectrometer_sc132/raspberrypi_v4l2/mv_tools_rpi/mv_mipi_i2c_new.sh"`
- Cloned to `/home/raspberry/`:  
  `"/home/raspberry/raspberrypi_v4l2/mv_tools_rpi/mv_mipi_i2c_new.sh"`

Check:

```bash
I2C_TOOL=$(jq -r '.paths.i2c_tool' /home/raspberry/env_config.json)
test -x "$I2C_TOOL" && echo "OK: $I2C_TOOL" || echo "FAIL: not executable or missing"
```

## 3. Run I2C tool manually

Run from the script’s directory so `./i2c_4read` and `./i2c_4write` resolve:

```bash
cd /home/raspberry/spectrometer_sc132/raspberrypi_v4l2/mv_tools_rpi
# Or: cd $(dirname "$I2C_TOOL")

./mv_mipi_i2c_new.sh -r metime -b 10
./mv_mipi_i2c_new.sh -r mgain -b 10
```

If you see `./i2c_4read: not found` or similar, the binaries are missing (see step 5).

Try a write:

```bash
./mv_mipi_i2c_new.sh -w expmode 0 -b 10
./mv_mipi_i2c_new.sh -w gainmode 0 -b 10
./mv_mipi_i2c_new.sh -w metime 20000 -b 10
./mv_mipi_i2c_new.sh -w mgain 4.0 -b 10
```

Use the bus number from `env_config.json` → `device.i2c_bus` (often `10`).

## 4. Check I2C bus number

`device.i2c_bus` must match the camera’s I2C bus. On Pi 5 it can differ from Pi 4.

```bash
ls /dev/i2c-*
i2cdetect -y 10
```

If the camera is on a different bus (e.g. `11`), update `env_config.json` → `device.i2c_bus`.

## 5. Compile I2C binaries (if missing)

`mv_mipi_i2c_new.sh` uses `./i2c_4read` and `./i2c_4write` in the same directory. These are built from source:

```bash
cd /home/raspberry/spectrometer_sc132/raspberrypi_v4l2/mv_tools_rpi/sources
./make.sh
ls -la ../i2c_4read ../i2c_4write
```

If `gcc` is missing: `sudo apt install build-essential`.

## 6. I2C permissions

The mqtt-camera service runs as `raspberry` (or configured user). That user needs I2C access:

```bash
groups raspberry
sudo usermod -aG i2c raspberry
# Log out and back in, or reboot
```

## 7. Streaming vs I2C timing

`apply_exposure_and_gain()` runs while rtsp-camera may be streaming. The V4L2 driver can hold the sensor; I2C writes during streaming may fail or be overwritten.

Test with stream off:

```bash
sudo systemctl stop rtsp-camera.service
# Send MQTT shutter/gain, or run I2C commands manually (step 3)
# Check if exposure/gain change
sudo systemctl start rtsp-camera.service
```

If it works with stream stopped, the issue is timing/contention during streaming.

## 8. Quick checklist

| Check | Command |
|-------|---------|
| Debug on | `jq '.debug' env_config.json` → `true` |
| Tool exists | `test -x "$(jq -r '.paths.i2c_tool' env_config.json)" && echo OK` |
| Binaries exist | `ls mv_tools_rpi/i2c_4read mv_tools_rpi/i2c_4write` |
| Manual read | `cd mv_tools_rpi && ./mv_mipi_i2c_new.sh -r metime -b 10` |
| I2C bus | `i2cdetect -y 10` |
| User in i2c | `groups | grep i2c` |

## 9. Code note: silent failures

`mqtt_camera_control.py` uses `stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL` for I2C subprocess calls, so errors are hidden. To capture them during debugging, temporarily change `apply_exposure_and_gain()` to use `capture_output=True` and log `result.stderr` on non-zero return.
