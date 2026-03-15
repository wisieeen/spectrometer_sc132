# Troubleshooting: Webserver Video Stream and Continuous Spectrum

When using the spectrometer webserver, you cannot activate the video stream or continuous spectrum acquisition. Single spectrum works. This doc covers causes and fixes.

---

## 1. Video stream: "4096 != 1392640" error

### Symptom

`rtsp-camera.service` is active but logs show:

```
4096 != 1392640
```

The HLS/RTSP stream produces no usable video.

### Cause

`start_rtsp.sh` uses `v4l2-ctl --stream-mmap --stream-to=-` when stride padding is detected (STRIDE_W ≠ WIDTH). The error means:

- **1392640** = expected frame size (e.g. 1280×1088 for Y8)
- **4096** = actual bytes written per buffer (often due to CMA / driver limits)

Typical causes:

1. **CMA too small** – Pi Zero 2W has limited contiguous memory; V4L2 mmap buffers may be smaller than needed.
2. **Driver buffer size** – Driver reports or allocates 4096-byte buffers instead of full-frame buffers.

### Fixes

**A. Use ffmpeg direct path (avoid v4l2-ctl pipe)**

When `STRIDE_W == WIDTH`, `start_rtsp.sh` uses `ffmpeg -f v4l2 -i $DEVICE` directly (no v4l2-ctl pipe). Try a resolution/format that avoids stride padding:

- Use **Y8** instead of Y10 if possible.
- Use a resolution where the driver reports no padding (e.g. 640×480, 1280×720 – depends on sensor).

Check stride:

```bash
v4l2-ctl -d /dev/video0 --get-fmt-video | grep -E "Width|Height|Bytes per Line"
```

If Bytes per Line ÷ bytes-per-pixel equals Width, you avoid the pipe path.

**B. Increase CMA**

Edit `/boot/config.txt` (or `/boot/firmware/config.txt` on newer Pi OS):

```
# Add or adjust (example for 256MB CMA)
cma=256M
```

Reboot. Check:

```bash
cat /proc/meminfo | grep Cma
```

**C. Try different resolution**

If 1080×640 causes stride padding, try 1280×720 or 640×480 in `camera_config.json` and restart rtsp-camera.

---

## 2. Continuous spectrum: won't start

### Symptom

- Single spectrum works.
- Start (continuous) does nothing or the page becomes unresponsive.

### Cause

`camera_capture.py` requires **rtsp-camera and mediamtx to be stopped** before any capture. If either is active, it calls `sys.exit(1)` and **terminates the webserver process**.

### Required workflow

1. **Stop the video stream first** – Click "RTSP Off" (or equivalent) in the webserver UI before starting continuous spectrum.
2. **Then** click "Start" for continuous spectrum.

### Verify stream is stopped

```bash
systemctl is-active rtsp-camera.service
systemctl is-active mediamtx.service
```

Both should return `inactive`. If either is `active`, stop it:

```bash
sudo systemctl stop rtsp-camera.service
sudo systemctl stop mediamtx.service
```

### If rtsp-camera starts at boot

The install enables `rtsp-camera.service` at boot, so the camera may be held by the stream from startup. In webserver mode:

1. Open the webserver UI.
2. Click "RTSP Off" to free the camera.
3. Use Single or Start (continuous) spectrum.

---

## 3. Webserver needs sudo for RTSP control

The webserver uses `sudo systemctl start/stop` for mediamtx and rtsp-camera. Ensure the sudoers entry exists:

```bash
sudo cat /etc/sudoers.d/spectrometer-sc132
```

Should include:

```
raspberry ALL=(ALL) NOPASSWD: /bin/systemctl start mediamtx.service, /bin/systemctl stop mediamtx.service, /bin/systemctl start rtsp-camera.service, /bin/systemctl stop rtsp-camera.service, /bin/systemctl restart rtsp-camera.service, ...
```

Replace `raspberry` with your install user if different.

---

## 4. Quick checklist

| Check | Command |
|-------|---------|
| RTSP status | `systemctl is-active rtsp-camera.service` |
| mediamtx status | `systemctl is-active mediamtx.service` |
| Stop stream | `sudo systemctl stop rtsp-camera mediamtx` |
| Stride / format | `v4l2-ctl -d /dev/video0 --get-fmt-video` |
| CMA size | `cat /proc/meminfo \| grep Cma` |
| Webserver logs | `journalctl -u spectrometer-webserver.service -f` |

---

## 5. Summary

- **Video stream broken**: Likely v4l2-ctl buffer/stride issue → try resolution/format without stride padding, or increase CMA.
- **Continuous spectrum fails**: Stop RTSP and mediamtx first; camera is exclusive to one use at a time.
