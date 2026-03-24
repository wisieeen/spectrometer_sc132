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

## 5. Video stream: ERR_CONNECTION_REFUSED or 404 on HLS (works in Home Assistant)

### Symptom

- Chrome console: `GET http://10.0.0.115:8888/mystream/index.m3u8 net::ERR_CONNECTION_REFUSED` or `404 (Not Found)`
- mediamtx and rtsp-camera services are active; stream works in Home Assistant
- Server: Raspberry Pi Zero 2W; client: Windows PC

### Why Home Assistant works but webserver does not

| Aspect | Home Assistant | Webserver |
|--------|----------------|-----------|
| Protocol | RTSP (port 8554) | HLS (port 8888) |
| Client | FFmpeg (native RTSP) | Browser (HLS.js or native HLS) |
| Timing | HA often connects after stream is ready | `loadStream()` runs immediately after "Start stream" |
| Retry | HA/FFmpeg may retry | No retry in frontend |

### Root causes (in order of likelihood)

**A. Race condition (most likely)**

mediamtx logs show:

```
[HLS] [muxer mystream] created (requested by 10.0.0.2:63668)
[HLS] [muxer mystream] destroyed: no stream is available on path 'mystream'
```

Sequence: User clicks "Start stream" → API starts mediamtx + rtsp-camera → `loadStream()` runs immediately → HLS request reaches mediamtx before ffmpeg has published → muxer created then destroyed → client gets 404.

rtsp-camera takes ~2 s to start ffmpeg and publish; the frontend does not wait or retry.

**B. ERR_CONNECTION_REFUSED**

- **Firewall**: Port 8888 may be blocked for external access while 8554 (RTSP) is open.
- **mediamtx not ready**: If HLS is requested before mediamtx finishes starting.
- **Wrong host in URL**: `env_config.json` `rtsp.url` host must match the Pi’s IP as seen from the client (e.g. `10.0.0.115`).

**C. HLS.js not loaded (Chrome/Edge/Firefox)**

The frontend uses `Hls.isSupported()` and `new Hls()`. **hls.js is not included in `index.html`** – only `app.js` is loaded. If `Hls` is undefined, the code falls back to `video.src = u.hls`. Chrome, Edge, and Firefox do not support native HLS; only Safari does. Without hls.js, HLS playback will fail on Windows. Add before `app.js`:

```html
<script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
```

### Investigation steps

1. **Confirm stream is published before HLS request**

   ```bash
   # On Pi: ensure stream is up, then test HLS from Windows
   curl -I http://10.0.0.115:8888/mystream/index.m3u8
   ```

   - 200: HLS works; issue is timing or frontend.
   - 404: Stream not ready or path wrong.
   - Connection refused: Firewall or mediamtx not listening.

2. **Check mediamtx HLS listener**

   ```bash
   sudo ss -tlnp | grep 8888
   # or
   sudo netstat -tlnp | grep 8888
   ```

   Should show mediamtx listening on `0.0.0.0:8888` or `*:8888`.

3. **Check firewall (if enabled)**

   ```bash
   sudo ufw status
   sudo iptables -L -n | grep 8888
   ```

   If ufw is active, allow 8888:

   ```bash
   sudo ufw allow 8888/tcp
   sudo ufw reload
   ```

4. **Verify rtsp.url host**

   ```bash
   # On Pi
   hostname -I
   # Compare with rtsp.url in env_config.json
   cat /home/raspberry/env_config.json | jq '.rtsp.url'
   ```

   Host in `rtsp.url` must be reachable from the Windows client.

5. **Test HLS with delay**

   - Click "Start stream".
   - Wait 5–10 seconds.
   - Click the "Video stream" tab (triggers `loadStream()` again).
   - If it works after waiting, the issue is timing.

### Recommended fixes

1. **Frontend: delay + retry** – After "Start stream", wait 3–5 s before calling `loadStream()`, and retry on 404/error (e.g. 3 attempts, 2 s apart).
2. **Frontend: poll for stream readiness** – Add an API or probe that checks if the path is available before loading HLS.
3. **Proxy HLS through webserver** – Serve HLS via the Flask app (same origin) to avoid CORS and simplify URL handling.
4. **Use WebRTC** – mediamtx supports WebRTC (port 8889); some browsers handle it better than HLS.
5. **Firewall** – Ensure port 8888 is allowed if ufw/iptables is enabled.

---

## 6. Summary

- **Video stream broken**: Likely v4l2-ctl buffer/stride issue → try resolution/format without stride padding, or increase CMA.
- **Continuous spectrum fails**: Stop RTSP and mediamtx first; camera is exclusive to one use at a time.
- **HLS 404 / ERR_CONNECTION_REFUSED**: Likely race (HLS requested before stream ready) or firewall; add delay/retry in frontend, verify port 8888, check rtsp.url host.
