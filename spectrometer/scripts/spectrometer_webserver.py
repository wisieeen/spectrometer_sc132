#!/usr/bin/env python3
"""
Spectrometer webserver: REST API and web UI for spectrometer control.
Runs spectrometer capture when webserver GPIO is enabled (no MQTT spectrometer service).
"""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request, send_from_directory

# Resolve static path relative to this script
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_STATIC_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "static")

from lib.config import load_spectrometer_config, save_spectrometer_config
from lib.env_config import load_env, load_camera_config
from lib.spectrum import extract_line_profile, fit_calibration, compute_spectrum
from lib.signal_processing import apply_dark_flat_frame, load_dark_flat, wiener_deconvolve
from scripts.camera_capture import capture_frame, capture_frames_averaged

app = Flask(__name__, static_folder=_STATIC_DIR, template_folder=os.path.join(os.path.dirname(_SCRIPT_DIR), "templates"))

# Spectrometer state (thread-safe)
_spectrum_lock = threading.Lock()
_last_spectra = {}  # channel_id -> spectrum dict
_running = False
_interval_ms = 1000


def _get_processing_cfg(spec_cfg=None):
    spec_cfg = spec_cfg or load_spectrometer_config()
    proc = spec_cfg.get("processing", {}) or {}
    try:
        frame_average_n = max(1, min(1000, int(proc.get("frame_average_n", 1))))
    except (TypeError, ValueError):
        frame_average_n = 1
    try:
        wiener_psf_sigma = max(0.5, min(20.0, float(proc.get("wiener_psf_sigma", 3.0))))
    except (TypeError, ValueError):
        wiener_psf_sigma = 3.0
    try:
        wiener_regularization = max(0.0001, min(1.0, float(proc.get("wiener_regularization", 0.01))))
    except (TypeError, ValueError):
        wiener_regularization = 0.01
    return {
        "frame_average_n": frame_average_n,
        "dark_flat_enabled": bool(proc.get("dark_flat_enabled", False)),
        "dark_frame_path": proc.get("dark_frame_path") or None,
        "flat_frame_path": proc.get("flat_frame_path") or None,
        "wiener_enabled": bool(proc.get("wiener_enabled", False)),
        "wiener_psf_sigma": wiener_psf_sigma,
        "wiener_regularization": wiener_regularization,
    }


def _acquire_frame(spec_cfg, dark, flat):
    proc = _get_processing_cfg(spec_cfg)
    n = max(1, proc["frame_average_n"])
    if n > 1:
        frame = capture_frames_averaged(n)
    else:
        frame = capture_frame()
        import numpy as np
        frame = frame.astype(np.float64)
    if proc["dark_flat_enabled"] and (dark is not None or flat is not None):
        frame = apply_dark_flat_frame(frame, dark, flat)
    return frame


def _process_frame_to_dict(frame, spec_cfg):
    import numpy as np
    from datetime import datetime, timezone

    cam_cfg = load_camera_config()
    meta = {"shutter_us": cam_cfg.get("shutter"), "gain_db": cam_cfg.get("gain")}
    calibrations = {
        c["id"]: c
        for c in spec_cfg.get("calibrations", [])
        if isinstance(c, dict) and isinstance(c.get("id"), str)
    }
    spectra = {}
    proc = _get_processing_cfg(spec_cfg)

    for ch in spec_cfg.get("channels", []):
        if not isinstance(ch, dict) or "id" not in ch:
            continue
        line = ch.get("line")
        if not line or "start" not in line or "end" not in line:
            continue
        try:
            start = (int(line["start"][0]), int(line["start"][1]))
            end = (int(line["end"][0]), int(line["end"][1]))
        except (TypeError, ValueError, IndexError):
            continue
        thickness = max(1, min(100, int(line.get("thickness", 5))))
        cal_id = ch.get("calibration_id", "default")
        cal = calibrations.get(cal_id)

        intensities = extract_line_profile(frame, start, end, thickness)
        if len(intensities) == 0:
            continue
        if proc["wiener_enabled"]:
            intensities = wiener_deconvolve(
                intensities,
                psf_sigma_px=proc["wiener_psf_sigma"],
                regularization=proc["wiener_regularization"],
            )
        if cal and "coefficients" in cal:
            coeffs = np.array(cal["coefficients"])
        elif cal and len(cal.get("pairs", [])) >= 2:
            coeffs = fit_calibration(
                [tuple(p) for p in cal["pairs"]],
                cal.get("fit", "linear"),
                cal.get("polynomial_degree", 2),
            )
        else:
            coeffs = np.array([1.0, 0.0])
        wavelengths, ints = compute_spectrum(intensities, coeffs)
        spectra[ch["id"]] = {
            "channel_id": ch["id"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "wavelengths_nm": wavelengths.tolist(),
            "intensities": ints.tolist(),
            "meta": meta,
        }
    return spectra


def _capture_loop():
    global _running, _last_spectra
    while True:
        if not _running:
            time.sleep(0.5)
            continue
        try:
            spec_cfg = load_spectrometer_config()
            proc = _get_processing_cfg(spec_cfg)
            dark, flat = load_dark_flat(proc["dark_frame_path"], proc["flat_frame_path"])
            frame = _acquire_frame(spec_cfg, dark, flat)
            spectra = _process_frame_to_dict(frame, spec_cfg)
            with _spectrum_lock:
                _last_spectra.update(spectra)
        except Exception as e:
            if os.environ.get("DEBUG"):
                print(f"spectrometer capture error: {e}", file=sys.stderr)
        interval = _interval_ms / 1000.0
        time.sleep(max(0.1, interval))


def _systemctl(action, unit):
    subprocess.run(["sudo", "systemctl", action, unit], check=False, timeout=15)


def _get_env():
    return load_env()


# --- Spectrometer API ---


@app.route("/api/spectrometer/start", methods=["POST"])
def api_spectrometer_start():
    global _running
    _running = True
    return jsonify({"status": "running"})


@app.route("/api/spectrometer/stop", methods=["POST"])
def api_spectrometer_stop():
    global _running
    _running = False
    return jsonify({"status": "idle"})


@app.route("/api/spectrometer/single", methods=["POST"])
def api_spectrometer_single():
    global _last_spectra
    try:
        spec_cfg = load_spectrometer_config()
        proc = _get_processing_cfg(spec_cfg)
        dark, flat = load_dark_flat(proc["dark_frame_path"], proc["flat_frame_path"])
        frame = _acquire_frame(spec_cfg, dark, flat)
        spectra = _process_frame_to_dict(frame, spec_cfg)
        with _spectrum_lock:
            _last_spectra.update(spectra)
        ch = next(iter(spectra.keys()), None)
        return jsonify(spectra.get(ch, {"status": "no channels"}))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/spectrometer/interval_ms", methods=["GET", "POST"])
def api_spectrometer_interval():
    global _interval_ms
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        val = data.get("value", data.get("interval_ms", request.form.get("value")))
        try:
            _interval_ms = max(100, min(3600000, int(val or 1000)))
        except (ValueError, TypeError):
            pass
    return jsonify({"interval_ms": _interval_ms})


@app.route("/api/spectrometer/processing_frame_average_n", methods=["GET", "POST"])
def api_processing_frame_average_n():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        val = data.get("value", request.form.get("value"))
        try:
            n = max(1, min(1000, int(val or 1)))
        except (ValueError, TypeError):
            n = 1
        spec_cfg = load_spectrometer_config()
        spec_cfg.setdefault("processing", {})["frame_average_n"] = n
        save_spectrometer_config(spec_cfg)
        return jsonify({"processing_frame_average_n": n})
    proc = _get_processing_cfg()
    return jsonify({"processing_frame_average_n": proc["frame_average_n"]})


@app.route("/api/spectrometer/processing_dark_flat_enabled", methods=["GET", "POST"])
def api_processing_dark_flat():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        val = data.get("value", request.form.get("value", "false"))
        enabled = str(val).lower() in ("true", "1", "on", "yes")
        spec_cfg = load_spectrometer_config()
        spec_cfg.setdefault("processing", {})["dark_flat_enabled"] = enabled
        save_spectrometer_config(spec_cfg)
        return jsonify({"processing_dark_flat_enabled": enabled})
    proc = _get_processing_cfg()
    return jsonify({"processing_dark_flat_enabled": proc["dark_flat_enabled"]})


@app.route("/api/spectrometer/processing_wiener_enabled", methods=["GET", "POST"])
def api_processing_wiener_enabled():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        val = data.get("value", request.form.get("value", "false"))
        enabled = str(val).lower() in ("true", "1", "on", "yes")
        spec_cfg = load_spectrometer_config()
        spec_cfg.setdefault("processing", {})["wiener_enabled"] = enabled
        save_spectrometer_config(spec_cfg)
        return jsonify({"processing_wiener_enabled": enabled})
    proc = _get_processing_cfg()
    return jsonify({"processing_wiener_enabled": proc["wiener_enabled"]})


@app.route("/api/spectrometer/processing_wiener_psf_sigma", methods=["GET", "POST"])
def api_processing_wiener_psf_sigma():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        val = data.get("value", request.form.get("value"))
        try:
            v = max(0.5, min(20.0, float(val or 3.0)))
        except (ValueError, TypeError):
            v = 3.0
        spec_cfg = load_spectrometer_config()
        spec_cfg.setdefault("processing", {})["wiener_psf_sigma"] = v
        save_spectrometer_config(spec_cfg)
        return jsonify({"processing_wiener_psf_sigma": v})
    proc = _get_processing_cfg()
    return jsonify({"processing_wiener_psf_sigma": proc["wiener_psf_sigma"]})


@app.route("/api/spectrometer/processing_wiener_regularization", methods=["GET", "POST"])
def api_processing_wiener_regularization():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        val = data.get("value", request.form.get("value"))
        try:
            v = max(0.0001, min(1.0, float(val or 0.01)))
        except (ValueError, TypeError):
            v = 0.01
        spec_cfg = load_spectrometer_config()
        spec_cfg.setdefault("processing", {})["wiener_regularization"] = v
        save_spectrometer_config(spec_cfg)
        return jsonify({"processing_wiener_regularization": v})
    proc = _get_processing_cfg()
    return jsonify({"processing_wiener_regularization": proc["wiener_regularization"]})


@app.route("/api/spectrometer/preview", methods=["POST"])
def api_spectrometer_preview():
    preview_script = os.path.join(os.path.dirname(__file__), "spectrometer_preview.py")
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    subprocess.Popen(
        [sys.executable, preview_script],
        cwd=project_dir,
        env=os.environ,
    )
    return jsonify({"status": "preview started"})


@app.route("/api/spectrometer/status", methods=["GET"])
def api_spectrometer_status():
    proc = _get_processing_cfg()
    with _spectrum_lock:
        channels = list(_last_spectra.keys())
    return jsonify({
        "status": "running" if _running else "idle",
        "interval_ms": _interval_ms,
        "channels": channels,
        "processing": proc,
    })


@app.route("/api/spectrometer/spectrum/<channel_id>", methods=["GET"])
def api_spectrometer_spectrum(channel_id):
    with _spectrum_lock:
        s = _last_spectra.get(channel_id)
    if s is None:
        return jsonify({"error": "no spectrum for channel"}), 404
    return jsonify(s)


# --- Camera / stream API (mirrors MQTT camera control) ---


def _load_camera_config():
    env = _get_env()
    path = env.get("paths", {}).get("camera_config", "/home/raspberry/camera_config.json")
    with open(path) as f:
        return json.load(f)


def _save_camera_config(cfg):
    env = _get_env()
    path = env.get("paths", {}).get("camera_config", "/home/raspberry/camera_config.json")
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)


def _apply_exposure_gain(cfg):
    env = _get_env()
    i2c_tool = env.get("paths", {}).get("i2c_tool", "")
    i2c_bus = str(env.get("device", {}).get("i2c_bus", "10"))
    if not i2c_tool or not os.path.isfile(i2c_tool) or not os.access(i2c_tool, os.X_OK):
        return
    i2c_dir = os.path.dirname(i2c_tool)
    fps = max(1, int(cfg.get("fps", 1)))
    shutter = int(cfg.get("shutter", 0))
    gain = cfg.get("gain", 0.0)
    max_exp = 1000000 // fps
    if shutter > max_exp:
        shutter = max_exp
    try:
        subprocess.run([i2c_tool, "-w", "expmode", "0", "-b", i2c_bus], cwd=i2c_dir, check=False, capture_output=True)
        subprocess.run([i2c_tool, "-w", "gainmode", "0", "-b", i2c_bus], cwd=i2c_dir, check=False, capture_output=True)
        if shutter > 0:
            subprocess.run([i2c_tool, "-w", "metime", str(shutter), "-b", i2c_bus], cwd=i2c_dir, check=False, capture_output=True)
        if gain is not None:
            subprocess.run([i2c_tool, "-w", "mgain", str(gain), "-b", i2c_bus], cwd=i2c_dir, check=False, capture_output=True)
    except Exception:
        pass


@app.route("/api/camera/config", methods=["GET"])
def api_camera_config():
    return jsonify(_load_camera_config())


@app.route("/api/camera/rtsp", methods=["POST"])
def api_camera_rtsp():
    env = _get_env()
    mediamtx = env.get("services", {}).get("mediamtx", "mediamtx.service")
    rtsp = env.get("services", {}).get("rtsp_camera", "rtsp-camera.service")
    data = request.get_json(silent=True) or {}
    action = data.get("action", "on").lower()
    if action in ("on", "start"):
        _systemctl("start", mediamtx)
        _systemctl("start", rtsp)
    else:
        _systemctl("stop", rtsp)
        _systemctl("stop", mediamtx)
    return jsonify({"rtsp": action})


@app.route("/api/camera/resolution", methods=["POST"])
def api_camera_resolution():
    cfg = _load_camera_config()
    data = request.get_json(silent=True) or {}
    val = data.get("value", data.get("resolution", ""))
    if val:
        cfg["resolution"] = str(val)
        _save_camera_config(cfg)
        env = _get_env()
        rtsp = env.get("services", {}).get("rtsp_camera", "rtsp-camera.service")
        _systemctl("restart", rtsp)
    return jsonify(cfg)


@app.route("/api/camera/fps", methods=["POST"])
def api_camera_fps():
    cfg = _load_camera_config()
    data = request.get_json(silent=True) or {}
    try:
        val = int(data.get("value", data.get("fps", cfg.get("fps", 5))))
    except (ValueError, TypeError):
        val = cfg.get("fps", 5)
    cfg["fps"] = val
    _save_camera_config(cfg)
    _apply_exposure_gain(cfg)
    env = _get_env()
    rtsp = env.get("services", {}).get("rtsp_camera", "rtsp-camera.service")
    _systemctl("restart", rtsp)
    return jsonify(cfg)


@app.route("/api/camera/shutter", methods=["POST"])
def api_camera_shutter():
    cfg = _load_camera_config()
    data = request.get_json(silent=True) or {}
    try:
        val = int(data.get("value", data.get("shutter", cfg.get("shutter", 0))))
    except (ValueError, TypeError):
        val = cfg.get("shutter", 0)
    cfg["shutter"] = val
    _save_camera_config(cfg)
    _apply_exposure_gain(cfg)
    return jsonify(cfg)


@app.route("/api/camera/gain", methods=["POST"])
def api_camera_gain():
    cfg = _load_camera_config()
    data = request.get_json(silent=True) or {}
    try:
        val = float(data.get("value", data.get("gain", cfg.get("gain", 0))))
    except (ValueError, TypeError):
        val = cfg.get("gain", 0)
    cfg["gain"] = val
    _save_camera_config(cfg)
    _apply_exposure_gain(cfg)
    return jsonify(cfg)


@app.route("/api/camera/pixel_format", methods=["POST"])
def api_camera_pixel_format():
    cfg = _load_camera_config()
    data = request.get_json(silent=True) or {}
    val = str(data.get("value", data.get("pixel_format", "Y8"))).upper()
    if val in ("8", "8BIT"):
        val = "Y8"
    elif val in ("10", "10BIT"):
        val = "Y10"
    if val in ("Y8", "Y10", "Y10P"):
        cfg["pixel_format"] = val
        _save_camera_config(cfg)
        env = _get_env()
        rtsp = env.get("services", {}).get("rtsp_camera", "rtsp-camera.service")
        _systemctl("restart", rtsp)
    return jsonify(cfg)


# --- Config API (WiFi, MQTT) - placeholder for task 5 ---


@app.route("/api/config/wifi", methods=["GET", "POST"])
def api_config_wifi():
    env = _get_env()
    wifi = env.get("wifi", {}) or {}
    sta_path = wifi.get("sta_config_path", "/etc/wpa_supplicant/wpa_supplicant.conf")
    if request.method == "POST":
        data = request.get_json(silent=True) or request.form
        ssid = data.get("ssid", "").strip()
        password = data.get("password", "")
        if not ssid:
            return jsonify({"error": "SSID required"}), 400
        # Write wpa_supplicant block (simplified - append network)
        try:
            content = f'''ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=US

network={{
\tssid="{ssid}"
\tpsk="{password}"
\tkey_mgmt=WPA-PSK
}}
'''
            # Write to project-local file; bootstrap can copy to system path
            project_dir = Path(env.get("paths", {}).get("home", "/home/raspberry"))
            local_path = project_dir / "wifi_credentials.conf"
            local_path.write_text(content, encoding="utf-8")
            return jsonify({"status": "saved", "path": str(local_path)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    # GET: return current config (masked)
    return jsonify({"sta_config_path": sta_path})


@app.route("/api/config/mqtt", methods=["GET", "POST"])
def api_config_mqtt():
    env_path = os.environ.get("ENV_CONFIG", "/home/raspberry/env_config.json")
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        try:
            with open(env_path) as f:
                env = json.load(f)
            mqtt = env.setdefault("mqtt", {})
            if "broker" in data:
                mqtt["broker"] = str(data["broker"])
            if "port" in data:
                mqtt["port"] = int(data["port"])
            if "user" in data:
                mqtt["user"] = str(data["user"])
            if "pass" in data:
                mqtt["pass"] = str(data["pass"])
            if "cmd_topic" in data:
                mqtt["cmd_topic"] = str(data["cmd_topic"])
            if "state_topic" in data:
                mqtt["state_topic"] = str(data["state_topic"])
            with open(env_path, "w") as f:
                json.dump(env, f, indent=2)
            return jsonify({"status": "saved"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    env = _get_env()
    mq = env.get("mqtt", {})
    return jsonify({
        "broker": mq.get("broker", ""),
        "port": mq.get("port", 1883),
        "user": mq.get("user", ""),
        "cmd_topic": mq.get("cmd_topic", ""),
        "state_topic": mq.get("state_topic", ""),
    })


@app.route("/api/stream/url", methods=["GET"])
def api_stream_url():
    """Return stream URL for video. mediamtx serves HLS on port 8888 by default."""
    env = _get_env()
    rtsp_url = env.get("rtsp", {}).get("url", "rtsp://localhost:8554/mystream")
    # Derive HLS URL: rtsp://host:8554/path -> http://host:8888/path
    try:
        from urllib.parse import urlparse
        p = urlparse(rtsp_url)
        host = p.hostname or "localhost"
        path = (p.path or "/mystream").strip("/") or "mystream"
        hls_url = f"http://{host}:8888/{path}"
        return jsonify({"hls": hls_url, "rtsp": rtsp_url})
    except Exception:
        return jsonify({"hls": "", "rtsp": rtsp_url})


@app.route("/api/theme", methods=["GET", "POST"])
def api_theme():
    themes = ["light", "dark", "high-contrast", "green-military"]
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        t = data.get("theme", request.form.get("theme", "light"))
        if t in themes:
            return jsonify({"theme": t})
    return jsonify({"themes": themes, "current": "light"})


# --- Static / index ---


@app.route("/")
def index():
    return send_from_directory(_STATIC_DIR, "index.html")


def main():
    t = threading.Thread(target=_capture_loop, daemon=True)
    t.start()

    env = _get_env()
    ws = env.get("webserver", {}) or {}
    host = ws.get("host", "0.0.0.0")
    port = int(ws.get("port", 8080))
    app.run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    main()
