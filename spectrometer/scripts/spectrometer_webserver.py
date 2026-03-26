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
import math
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, request, send_from_directory

# Resolve static path relative to this script
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_STATIC_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "static")

from lib.config import load_spectrometer_config, save_spectrometer_config, get_processing_cfg
from lib.env_config import load_env, load_camera_config, save_camera_config, DEFAULT_ENV_CONFIG
from lib.spectrum import extract_line_profile, fit_calibration, compute_spectrum
from lib.signal_processing import (
    apply_dark_flat_frame,
    load_dark_flat,
    richardson_lucy_deconvolve,
)
from scripts.camera_capture import (
    capture_frame,
    capture_frames_averaged,
    invalidate_capture_context_cache,
)

app = Flask(__name__, static_folder=_STATIC_DIR, template_folder=os.path.join(os.path.dirname(_SCRIPT_DIR), "templates"))

# Spectrometer state (thread-safe)
_spectrum_lock = threading.Lock()
_last_spectra = {}  # channel_id -> spectrum dict
_running = False
_interval_ms = 1000
_reload_dark_flat_on_next_cycle = True
_dark_flat_cache = {
    "dark": None,
    "flat": None,
    "dark_path": None,
    "flat_path": None,
    "valid": False,
}


def _capture_calibration_frame(mode):
    """Capture and save dark/flat calibration frame using current config paths.

    Inputs:
        mode: "dark" or "flat".
    Output:
        Tuple (payload_dict, status_code).
    Transformation:
        Uses `processing.dark_frame_path` / `processing.flat_frame_path` from config,
        captures averaged frames, saves `.npy`, and marks dark/flat cache for reload.
    """
    global _reload_dark_flat_on_next_cycle
    if mode not in ("dark", "flat"):
        return {"error": "mode must be 'dark' or 'flat'"}, 400
    if _running:
        return {"error": "stop continuous acquisition before collecting calibration frame"}, 409

    spec_cfg = load_spectrometer_config()
    proc = get_processing_cfg(spec_cfg)
    output_path = proc["dark_frame_path"] if mode == "dark" else proc["flat_frame_path"]
    n = max(2, int(proc.get("frame_average_n", 1)))

    try:
        invalidate_capture_context_cache()
        frame = capture_frames_averaged(n)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        import numpy as np

        np.save(str(out), frame)
        _reload_dark_flat_on_next_cycle = True
        return {
            "status": "saved",
            "mode": mode,
            "path": str(out),
            "frames_averaged": n,
            "shape": list(frame.shape),
        }, 200
    except Exception as e:
        return {"error": str(e)}, 500


def _fps_from_shutter_us(shutter_us):
    sh = max(1, int(shutter_us))
    return max(1, min(30, int(math.ceil(1_000_000.0 / float(sh)))))


def _load_dark_flat_cached(proc, cache, force_reload=False):
    """Load dark/flat using RAM cache; refresh on path change or force_reload."""
    dark_path = proc["dark_frame_path"]
    flat_path = proc["flat_frame_path"]
    cache_miss = (
        force_reload
        or (not cache["valid"])
        or cache["dark_path"] != dark_path
        or cache["flat_path"] != flat_path
    )
    if cache_miss:
        dark, flat = load_dark_flat(dark_path, flat_path)
        cache["dark"] = dark
        cache["flat"] = flat
        cache["dark_path"] = dark_path
        cache["flat_path"] = flat_path
        cache["valid"] = True
    return cache["dark"], cache["flat"], cache_miss


def _is_timing_enabled(env):
    """Return True when continuous-loop timing profiler is enabled."""
    raw = os.environ.get("SPECTROMETER_TIMING_PROFILE")
    if raw is None:
        raw = env.get("spectrometer", {}).get("timing_profile_enabled", False)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _timing_log_path(env):
    """Resolve CSV timing log path (prefer SD card path)."""
    configured = env.get("spectrometer", {}).get("timing_log_path")
    if configured:
        return Path(str(configured))
    return Path("/media/sdcard/spectrometer_timing.csv")


def _append_timing_row(path, row):
    """Append one CSV row to timing file. Fail-open on IO errors."""
    header = [
        "timestamp_utc",
        "cycle_id",
        "step",
        "channel_id",
        "duration_ms",
        "interval_ms",
        "frame_average_n",
        "dark_flat_enabled",
        "richardson_lucy_enabled",
        "channels_configured",
    ]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = (not path.exists()) or (path.stat().st_size == 0)
        with path.open("a", encoding="utf-8", buffering=1) as f:
            if write_header:
                f.write(",".join(header) + "\n")
            f.write(
                f'{row["timestamp_utc"]},{row["cycle_id"]},{row["step"]},{row["channel_id"]},'
                f'{row["duration_ms"]:.3f},{row["interval_ms"]},{row["frame_average_n"]},'
                f'{row["dark_flat_enabled"]},{row["richardson_lucy_enabled"]},{row["channels_configured"]}\n'
            )
    except Exception:
        # Profiling is temporary/diagnostic and must never stop acquisition.
        pass


def _acquire_frame(spec_cfg, dark, flat, timing_rows=None):
    """Capture one spectrometer frame and optionally apply corrections.

    Inputs:
        spec_cfg: Full spectrometer configuration dict (used to read `processing` settings).
        dark: Dark frame correction array (or None).
        flat: Flat frame correction array (or None).
    Output:
        A floating-point 2D frame array (NumPy) ready for spectrum extraction.
    Transformation:
        Captures either a single frame or `frame_average_n` frames, averages them if needed,
        converts to float, and applies dark/flat correction when enabled and frames are available.
    """
    proc = get_processing_cfg(spec_cfg)
    n = max(1, proc["frame_average_n"])
    t0 = time.perf_counter_ns()
    if n > 1:
        frame = capture_frames_averaged(n, timing_rows=timing_rows)
        if timing_rows is not None:
            timing_rows.append(
                {
                    "step": "capture_frames_averaged",
                    "channel_id": "",
                    "duration_ms": (time.perf_counter_ns() - t0) / 1_000_000.0,
                }
            )
    else:
        t1 = time.perf_counter_ns()
        frame = capture_frame()
        if timing_rows is not None:
            timing_rows.append(
                {
                    "step": "capture_frame",
                    "channel_id": "",
                    "duration_ms": (time.perf_counter_ns() - t1) / 1_000_000.0,
                }
            )
        import numpy as np
        t2 = time.perf_counter_ns()
        frame = frame.astype(np.float64)
        if timing_rows is not None:
            timing_rows.append(
                {
                    "step": "capture_frame.astype_float64",
                    "channel_id": "",
                    "duration_ms": (time.perf_counter_ns() - t2) / 1_000_000.0,
                }
            )
    if proc["dark_flat_enabled"] and (dark is not None or flat is not None):
        t3 = time.perf_counter_ns()
        frame = apply_dark_flat_frame(frame, dark, flat)
        if timing_rows is not None:
            timing_rows.append(
                {
                    "step": "apply_dark_flat_frame",
                    "channel_id": "",
                    "duration_ms": (time.perf_counter_ns() - t3) / 1_000_000.0,
                }
            )
    elif timing_rows is not None:
        timing_rows.append(
            {
                "step": "apply_dark_flat_frame_skipped",
                "channel_id": "",
                "duration_ms": 0.0,
            }
        )
    return frame


def _process_frame_to_dict(frame, spec_cfg, dark=None, flat=None, timing_rows=None):
    """Extract spectra for all configured channels from a frame.

    Inputs:
        frame: Captured frame array (as produced by `_acquire_frame`).
        spec_cfg: Spectrometer configuration dict (channels + calibration + processing settings).
        dark: Dark correction frame array (or None); used only for metadata/flagging.
        flat: Flat correction frame array (or None); used only for metadata/flagging.
    Output:
        Dict mapping `channel_id` -> `spectrum` dict:
            { "channel_id", "timestamp", "wavelengths_nm", "intensities", "meta" }.
    Transformation:
        For each channel region-of-interest, extracts a line profile, optionally runs
        Richardson–Lucy deconvolution, converts pixels to wavelengths via calibration
        (coefficients or fitted pairs), computes the final spectrum, and aggregates results.
    """
    import numpy as np

    cam_cfg = load_camera_config()
    pixel_format = str(cam_cfg.get("pixel_format", "Y8")).strip().upper()
    if pixel_format in ("GREY",):
        pixel_format = "Y8"
    max_value = 255.0 if pixel_format == "Y8" else 1023.0 if pixel_format in ("Y10", "Y10P") else None
    proc = get_processing_cfg(spec_cfg)
    timing = timing_rows
    meta = {
        "shutter_us": cam_cfg.get("shutter"),
        "gain_db": cam_cfg.get("gain"),
        "processing": {
            "frame_average_n": proc["frame_average_n"],
            "dark_flat_applied": proc["dark_flat_enabled"] and (dark is not None or flat is not None),
            "richardson_lucy_applied": proc["richardson_lucy_enabled"],
        },
    }
    calibrations = {
        c["id"]: c
        for c in spec_cfg.get("calibrations", [])
        if isinstance(c, dict) and isinstance(c.get("id"), str)
    }
    spectra = {}

    for ch in spec_cfg.get("channels", []):
        if not isinstance(ch, dict) or "id" not in ch:
            continue
        if not bool(ch.get("active", True)):
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

        t0 = time.perf_counter_ns()
        line_result = extract_line_profile(
            frame,
            start,
            end,
            thickness,
            max_value=max_value,
            overexposure_margin=5,
            return_overexposed=bool(spec_cfg.get("_single_capture_overexposure_check", False)),
        )
        if isinstance(line_result, tuple):
            intensities, overexposed = line_result
        else:
            intensities = line_result
            overexposed = None
        if timing is not None:
            timing.append(
                {
                    "step": "extract_line_profile",
                    "channel_id": ch.get("id", ""),
                    "duration_ms": (time.perf_counter_ns() - t0) / 1_000_000.0,
                }
            )
        if len(intensities) == 0:
            continue
        if proc["richardson_lucy_enabled"]:
            t0 = time.perf_counter_ns()
            intensities = richardson_lucy_deconvolve(
                intensities,
                psf_sigma_px=proc["richardson_lucy_psf_sigma"],
                num_iterations=proc["richardson_lucy_iterations"],
                psf_path=proc.get("richardson_lucy_psf_path"),
            )
            if timing is not None:
                timing.append(
                    {
                        "step": "richardson_lucy_deconvolve",
                        "channel_id": ch.get("id", ""),
                        "duration_ms": (time.perf_counter_ns() - t0) / 1_000_000.0,
                    }
                )
        t0 = time.perf_counter_ns()
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
        if timing is not None:
            timing.append(
                {
                    "step": "compute_calibration_coeffs",
                    "channel_id": ch.get("id", ""),
                    "duration_ms": (time.perf_counter_ns() - t0) / 1_000_000.0,
                }
            )
        t0 = time.perf_counter_ns()
        wavelengths, ints = compute_spectrum(intensities, coeffs)
        if timing is not None:
            timing.append(
                {
                    "step": "compute_spectrum",
                    "channel_id": ch.get("id", ""),
                    "duration_ms": (time.perf_counter_ns() - t0) / 1_000_000.0,
                }
            )
        channel_meta = dict(meta)
        if overexposed is not None:
            channel_meta["overexposure"] = {
                "checked": True,
                "overexposed": bool(overexposed),
                "threshold": (max_value - 5.0) if max_value is not None else None,
                "max_value": max_value,
            }
        spectra[ch["id"]] = {
            "channel_id": ch["id"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "wavelengths_nm": wavelengths.tolist(),
            "intensities": ints.tolist(),
            "meta": channel_meta,
        }
    return spectra


def _capture_loop():
    """Background loop that repeatedly captures and processes spectra while running.

    Inputs/Globals:
        Uses module globals:
            _running (bool), _interval_ms (int), _last_spectra (dict), _spectrum_lock (Lock).
    Output:
        None (updates `_last_spectra` in-place).
    Transformation:
        When `_running` is True, loads the latest spectrometer + processing config,
        captures a frame with dark/flat correction, converts it into per-channel spectra,
        and atomically updates `_last_spectra`.
    """
    global _running, _last_spectra, _reload_dark_flat_on_next_cycle, _dark_flat_cache
    env = _get_env()
    timing_enabled = _is_timing_enabled(env)
    timing_path = _timing_log_path(env)
    cycle_id = 0
    while True:
        cycle_start_ns = time.perf_counter_ns()
        if not _running:
            time.sleep(0.5)
            continue
        try:
            timing_rows = []

            t0 = time.perf_counter_ns()
            spec_cfg = load_spectrometer_config()
            if timing_enabled:
                timing_rows.append({"step": "load_spectrometer_config", "channel_id": "", "duration_ms": (time.perf_counter_ns() - t0) / 1_000_000.0})

            t0 = time.perf_counter_ns()
            proc = get_processing_cfg(spec_cfg)
            if timing_enabled:
                timing_rows.append({"step": "get_processing_cfg", "channel_id": "", "duration_ms": (time.perf_counter_ns() - t0) / 1_000_000.0})

            t0 = time.perf_counter_ns()
            dark, flat, cache_miss = _load_dark_flat_cached(
                proc,
                _dark_flat_cache,
                force_reload=_reload_dark_flat_on_next_cycle,
            )
            _reload_dark_flat_on_next_cycle = False
            if timing_enabled:
                timing_rows.append({"step": "load_dark_flat", "channel_id": "", "duration_ms": (time.perf_counter_ns() - t0) / 1_000_000.0})
                timing_rows.append({"step": "load_dark_flat_cache_miss" if cache_miss else "load_dark_flat_cache_hit", "channel_id": "", "duration_ms": 0.0})

            t0 = time.perf_counter_ns()
            frame = _acquire_frame(spec_cfg, dark, flat, timing_rows=timing_rows if timing_enabled else None)
            if timing_enabled:
                timing_rows.append({"step": "_acquire_frame", "channel_id": "", "duration_ms": (time.perf_counter_ns() - t0) / 1_000_000.0})

            t0 = time.perf_counter_ns()
            spectra = _process_frame_to_dict(frame, spec_cfg, dark=dark, flat=flat, timing_rows=timing_rows if timing_enabled else None)
            if timing_enabled:
                timing_rows.append({"step": "_process_frame_total", "channel_id": "", "duration_ms": (time.perf_counter_ns() - t0) / 1_000_000.0})

            with _spectrum_lock:
                _last_spectra = spectra
            if timing_enabled:
                cycle_id += 1
                rows_common = {
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "cycle_id": cycle_id,
                    "interval_ms": _interval_ms,
                    "frame_average_n": proc["frame_average_n"],
                    "dark_flat_enabled": str(proc["dark_flat_enabled"]).lower(),
                    "richardson_lucy_enabled": str(proc["richardson_lucy_enabled"]).lower(),
                    "channels_configured": len(spec_cfg.get("channels", [])),
                }
                for row in timing_rows:
                    _append_timing_row(
                        timing_path,
                        {
                            **rows_common,
                            "step": row["step"],
                            "channel_id": row["channel_id"],
                            "duration_ms": row["duration_ms"],
                        },
                    )
        except Exception as e:
            if os.environ.get("DEBUG"):
                print(f"spectrometer capture error: {e}", file=sys.stderr)
        interval = _interval_ms / 1000.0
        time.sleep(max(0.1, interval))
        if timing_enabled and _running:
            _append_timing_row(
                timing_path,
                {
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "cycle_id": cycle_id,
                    "step": "cycle_total_with_sleep",
                    "channel_id": "",
                    "duration_ms": (time.perf_counter_ns() - cycle_start_ns) / 1_000_000.0,
                    "interval_ms": _interval_ms,
                    "frame_average_n": proc["frame_average_n"],
                    "dark_flat_enabled": str(proc["dark_flat_enabled"]).lower(),
                    "richardson_lucy_enabled": str(proc["richardson_lucy_enabled"]).lower(),
                    "channels_configured": len(spec_cfg.get("channels", [])),
                },
            )


def _systemctl(action, unit):
    """Run `sudo systemctl <action> <unit>` with best-effort failure handling.

    Inputs:
        action: systemd action (e.g. "start", "stop", "restart").
        unit: unit name (e.g. "rtsp-camera.service").
    Output:
        None (errors are not raised; failures are ignored).
    Transformation:
        Side-effect only: starts/stops/restarts system services.
    """
    subprocess.run(["sudo", "systemctl", action, unit], check=False, timeout=15)


def _get_env():
    """Load the environment configuration dict used by the webserver.

    Output:
        Dict loaded by `load_env()`.
    Transformation:
        None; wrapper for readability.
    """
    return load_env()


# --- Spectrometer API ---


@app.route("/api/spectrometer/start", methods=["POST"])
def api_spectrometer_start():
    """HTTP endpoint: start continuous spectrometer capture.

    Inputs:
        POST request with optional payload (ignored).
    Output:
        JSON {"status": "running"}.
    Transformation:
        Sets `_running = True` so `_capture_loop()` begins capturing spectra.
    """
    global _running, _reload_dark_flat_on_next_cycle
    _running = True
    _reload_dark_flat_on_next_cycle = True
    invalidate_capture_context_cache()
    return jsonify({"status": "running"})


@app.route("/api/spectrometer/stop", methods=["POST"])
def api_spectrometer_stop():
    """HTTP endpoint: stop continuous spectrometer capture.

    Inputs:
        POST request with optional payload (ignored).
    Output:
        JSON {"status": "idle"}.
    Transformation:
        Sets `_running = False` so `_capture_loop()` pauses spectrum capture.
    """
    global _running
    _running = False
    return jsonify({"status": "idle"})


@app.route("/api/spectrometer/single", methods=["POST"])
def api_spectrometer_single():
    """HTTP endpoint: capture and process exactly one spectrum snapshot.

    Inputs:
        POST request with optional payload (ignored); uses current configs on disk.
    Output:
        On success: JSON spectrum dict for the first channel produced,
        or {"status": "no channels"} if no spectra were generated.
        On failure: JSON {"error": "..."} with HTTP 500.
    Transformation:
        Captures a frame (with latest dark/flat + processing settings) and processes it
        into per-channel spectra; updates `_last_spectra`.
    """
    global _last_spectra, _reload_dark_flat_on_next_cycle, _dark_flat_cache
    try:
        env = _get_env()
        timing_enabled = _is_timing_enabled(env)
        timing_path = _timing_log_path(env)
        timing_rows = [] if timing_enabled else None

        _reload_dark_flat_on_next_cycle = True
        invalidate_capture_context_cache()
        spec_cfg = load_spectrometer_config()
        proc = get_processing_cfg(spec_cfg)
        dark, flat, _ = _load_dark_flat_cached(proc, _dark_flat_cache, force_reload=True)
        _reload_dark_flat_on_next_cycle = False
        t0 = time.perf_counter_ns()
        frame = _acquire_frame(spec_cfg, dark, flat, timing_rows=timing_rows)
        if timing_enabled:
            timing_rows.append(
                {
                    "step": "_single_acquire_frame_total",
                    "channel_id": "",
                    "duration_ms": (time.perf_counter_ns() - t0) / 1_000_000.0,
                }
            )
        spec_cfg = dict(spec_cfg)
        spec_cfg["_single_capture_overexposure_check"] = True
        t0 = time.perf_counter_ns()
        spectra = _process_frame_to_dict(frame, spec_cfg, dark=dark, flat=flat, timing_rows=timing_rows)
        if timing_enabled:
            timing_rows.append(
                {
                    "step": "_single_process_frame_total",
                    "channel_id": "",
                    "duration_ms": (time.perf_counter_ns() - t0) / 1_000_000.0,
                }
            )
        with _spectrum_lock:
            _last_spectra = spectra
        if timing_enabled:
            cycle_id = int(time.time() * 1000)
            rows_common = {
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "cycle_id": cycle_id,
                "interval_ms": _interval_ms,
                "frame_average_n": proc["frame_average_n"],
                "dark_flat_enabled": str(proc["dark_flat_enabled"]).lower(),
                "richardson_lucy_enabled": str(proc["richardson_lucy_enabled"]).lower(),
                "channels_configured": len(spec_cfg.get("channels", [])),
            }
            for row in timing_rows:
                _append_timing_row(
                    timing_path,
                    {
                        **rows_common,
                        "step": row["step"],
                        "channel_id": row["channel_id"],
                        "duration_ms": row["duration_ms"],
                    },
                )
        ch = next(iter(spectra.keys()), None)
        return jsonify(spectra.get(ch, {"status": "no channels"}))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/spectrometer/interval_ms", methods=["GET", "POST"])
def api_spectrometer_interval():
    """HTTP endpoint: get or set the capture interval in milliseconds.

    Inputs:
        GET: none.
        POST: JSON or form data containing:
            - `value` or `interval_ms` (interpreted as integer ms).
    Output:
        JSON {"interval_ms": <int>}.
    Transformation:
        Updates `_interval_ms` with bounds [100, 3600000] and stores it in memory only.
    """
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
    """HTTP endpoint: get or set `processing.frame_average_n`.

    Inputs:
        GET: none.
        POST: JSON or form data containing `value` (integer; clamped to [1, 1000]).
    Output:
        JSON {"processing_frame_average_n": <int>}.
    Transformation:
        Updates the spectrometer config file on disk and returns the clamped value.
    """
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
    proc = get_processing_cfg()
    return jsonify({"processing_frame_average_n": proc["frame_average_n"]})


@app.route("/api/spectrometer/processing_dark_flat_enabled", methods=["GET", "POST"])
def api_processing_dark_flat():
    """HTTP endpoint: get or set `processing.dark_flat_enabled`.

    Inputs:
        GET: none.
        POST: JSON or form data containing `value` boolean-like string.
    Output:
        JSON {"processing_dark_flat_enabled": "true"/"false"} (as string).
    Transformation:
        Updates the spectrometer config file on disk and returns the derived boolean.
    """
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        val = data.get("value", request.form.get("value", "false"))
        enabled = str(val).lower() in ("true", "1", "on", "yes")
        spec_cfg = load_spectrometer_config()
        spec_cfg.setdefault("processing", {})["dark_flat_enabled"] = enabled
        save_spectrometer_config(spec_cfg)
        return jsonify({"processing_dark_flat_enabled": enabled})
    proc = get_processing_cfg()
    return jsonify({"processing_dark_flat_enabled": proc["dark_flat_enabled"]})


@app.route("/api/spectrometer/processing_richardson_lucy_enabled", methods=["GET", "POST"])
def api_processing_richardson_lucy_enabled():
    """HTTP endpoint: get or set `processing.richardson_lucy_enabled`.

    Inputs:
        GET: none.
        POST: JSON or form data containing `value` boolean-like string.
    Output:
        JSON {"processing_richardson_lucy_enabled": "true"/"false"} (as string).
    Transformation:
        Updates the spectrometer config file on disk and returns the derived boolean.
    """
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        val = data.get("value", request.form.get("value", "false"))
        enabled = str(val).lower() in ("true", "1", "on", "yes")
        spec_cfg = load_spectrometer_config()
        spec_cfg.setdefault("processing", {})["richardson_lucy_enabled"] = enabled
        save_spectrometer_config(spec_cfg)
        return jsonify({"processing_richardson_lucy_enabled": enabled})
    proc = get_processing_cfg()
    return jsonify({"processing_richardson_lucy_enabled": proc["richardson_lucy_enabled"]})


@app.route("/api/spectrometer/processing_richardson_lucy_psf_sigma", methods=["GET", "POST"])
def api_processing_richardson_lucy_psf_sigma():
    """HTTP endpoint: get or set `processing.richardson_lucy_psf_sigma`.

    Inputs:
        GET: none.
        POST: JSON or form data containing `value` convertible to float
              (clamped to [0.5, 20.0]).
    Output:
        JSON {"processing_richardson_lucy_psf_sigma": <float>}.
    Transformation:
        Updates the spectrometer config file on disk and returns the clamped value.
    """
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        val = data.get("value", request.form.get("value"))
        try:
            v = max(0.5, min(20.0, float(val or 3.0)))
        except (ValueError, TypeError):
            v = 3.0
        spec_cfg = load_spectrometer_config()
        spec_cfg.setdefault("processing", {})["richardson_lucy_psf_sigma"] = v
        save_spectrometer_config(spec_cfg)
        return jsonify({"processing_richardson_lucy_psf_sigma": v})
    proc = get_processing_cfg()
    return jsonify({"processing_richardson_lucy_psf_sigma": proc["richardson_lucy_psf_sigma"]})


@app.route("/api/spectrometer/processing_richardson_lucy_iterations", methods=["GET", "POST"])
def api_processing_richardson_lucy_iterations():
    """HTTP endpoint: get or set `processing.richardson_lucy_iterations`.

    Inputs:
        GET: none.
        POST: JSON or form data containing `value` integer
              (clamped to [1, 100]).
    Output:
        JSON {"processing_richardson_lucy_iterations": <int>}.
    Transformation:
        Updates the spectrometer config file on disk and returns the clamped value.
    """
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        val = data.get("value", request.form.get("value"))
        try:
            v = max(1, min(100, int(val or 15)))
        except (ValueError, TypeError):
            v = 15
        spec_cfg = load_spectrometer_config()
        spec_cfg.setdefault("processing", {})["richardson_lucy_iterations"] = v
        save_spectrometer_config(spec_cfg)
        return jsonify({"processing_richardson_lucy_iterations": v})
    proc = get_processing_cfg()
    return jsonify({"processing_richardson_lucy_iterations": proc["richardson_lucy_iterations"]})


@app.route("/api/spectrometer/processing_richardson_lucy_psf_path", methods=["GET", "POST"])
def api_processing_richardson_lucy_psf_path():
    """HTTP endpoint: get or set `processing.richardson_lucy_psf_path`.

    Inputs:
        GET: none.
        POST: JSON or form data containing `value` (string path; empty => null in config).
    Output:
        JSON {"processing_richardson_lucy_psf_path": <path or null-like empty string>}.
    Transformation:
        Updates the spectrometer config file on disk and returns the stored value.
    """
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        val = data.get("value", request.form.get("value", ""))
        path = str(val).strip() if val is not None else ""
        spec_cfg = load_spectrometer_config()
        spec_cfg.setdefault("processing", {})["richardson_lucy_psf_path"] = path or None
        save_spectrometer_config(spec_cfg)
        return jsonify({"processing_richardson_lucy_psf_path": path or None})
    proc = get_processing_cfg()
    return jsonify({"processing_richardson_lucy_psf_path": proc.get("richardson_lucy_psf_path") or ""})


@app.route("/api/spectrometer/preview", methods=["POST"])
def api_spectrometer_preview():
    """HTTP endpoint: start a preview script in a separate process.

    Inputs:
        POST request with optional payload (ignored).
    Output:
        JSON {"status": "preview started"}.
    Transformation:
        Spawns `spectrometer_preview.py` via `subprocess.Popen` using the current environment.
    """
    preview_script = os.path.join(os.path.dirname(__file__), "spectrometer_preview.py")
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    subprocess.Popen(
        [sys.executable, preview_script],
        cwd=project_dir,
        env=os.environ,
    )
    return jsonify({"status": "preview started"})


@app.route("/api/spectrometer/capture_dark_frame", methods=["POST"])
def api_capture_dark_frame():
    """HTTP endpoint: capture and save dark-frame calibration data."""
    payload, status = _capture_calibration_frame("dark")
    return jsonify(payload), status


@app.route("/api/spectrometer/capture_flat_frame", methods=["POST"])
def api_capture_flat_frame():
    """HTTP endpoint: capture and save flat-frame calibration data."""
    payload, status = _capture_calibration_frame("flat")
    return jsonify(payload), status


@app.route("/api/spectrometer/status", methods=["GET"])
def api_spectrometer_status():
    """HTTP endpoint: return current capture status and last known channels.

    Inputs:
        GET: none.
    Output:
        JSON with:
            - status ("running"|"idle")
            - interval_ms (int)
            - channels (list of channel ids)
            - processing (processing config dict)
    Transformation:
        Reads `_running`, `_interval_ms`, `_last_spectra` under lock, and returns current configs.
    """
    proc = get_processing_cfg()
    spec_cfg = load_spectrometer_config()
    channel_activity = {}
    for ch in spec_cfg.get("channels", []):
        if isinstance(ch, dict) and isinstance(ch.get("id"), str):
            channel_activity[ch["id"]] = bool(ch.get("active", True))
    with _spectrum_lock:
        channels = list(_last_spectra.keys())
    return jsonify({
        "status": "running" if _running else "idle",
        "interval_ms": _interval_ms,
        "channels": channels,
        "channel_activity": channel_activity,
        "processing": proc,
    })


@app.route("/api/spectrometer/channel_active", methods=["POST"])
def api_spectrometer_channel_active():
    """HTTP endpoint: set per-channel active flag used by spectrum processing."""
    data = request.get_json(silent=True) or {}
    channel_id = str(data.get("channel_id", "")).strip()
    active = bool(data.get("active", True))
    if not channel_id:
        return jsonify({"error": "channel_id required"}), 400
    spec_cfg = load_spectrometer_config()
    found = False
    for ch in spec_cfg.get("channels", []):
        if isinstance(ch, dict) and ch.get("id") == channel_id:
            ch["active"] = active
            found = True
            break
    if not found:
        return jsonify({"error": "channel not found"}), 404
    save_spectrometer_config(spec_cfg)
    return jsonify({"channel_id": channel_id, "active": active})


@app.route("/api/spectrometer/spectrum/<channel_id>", methods=["GET"])
def api_spectrometer_spectrum(channel_id):
    """HTTP endpoint: return the last computed spectrum for a specific channel.

    Inputs:
        channel_id: channel id from the URL path.
    Output:
        On success: spectrum JSON for that channel.
        If missing: JSON {"error": "no spectrum for channel"} with HTTP 404.
    Transformation:
        Reads `_last_spectra` under lock without modifying it.
    """
    with _spectrum_lock:
        s = _last_spectra.get(channel_id)
    if s is None:
        return jsonify({"error": "no spectrum for channel"}), 404
    return jsonify(s)


# --- Camera / stream API (mirrors MQTT camera control) ---


def _apply_exposure_gain(cfg):
    """Apply camera exposure/gain using the configured I2C tool (if available).

    Inputs:
        cfg: Camera configuration values dict containing (at least) fps, shutter, gain.
    Output:
        None (side-effect only).
    Transformation:
        If `paths.i2c_tool` exists and is executable, clamps shutter to maximum exposure
        computed from fps and uses the tool to set exposure mode, gain mode, metime,
        and mgain.
    """
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
    """HTTP endpoint: return the current camera configuration.

    Inputs:
        GET: none.
    Output:
        JSON camera config dict (as loaded from camera config file).
    Transformation:
        None; read-only endpoint.
    """
    return jsonify(load_camera_config())


@app.route("/api/camera/rtsp", methods=["POST"])
def api_camera_rtsp():
    """HTTP endpoint: start or stop RTSP services (mediamtx + rtsp-camera).

    Inputs:
        POST JSON body containing `action` (defaults to "on").
        Accepted: "on"/"start" => start services; otherwise stop services.
    Output:
        JSON {"rtsp": <action>}.
    Transformation:
        Starts or stops systemd units defined in env config.
    """
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
    """HTTP endpoint: set camera resolution and restart RTSP camera service.

    Inputs:
        POST JSON body containing `value` (resolution string).
    Output:
        JSON updated camera config dict.
    Transformation:
        Updates `resolution` in camera config file and restarts the RTSP camera service.
    """
    cfg = load_camera_config()
    data = request.get_json(silent=True) or {}
    val = data.get("value", data.get("resolution", ""))
    if val:
        cfg["resolution"] = str(val)
        save_camera_config(cfg)
        env = _get_env()
        rtsp = env.get("services", {}).get("rtsp_camera", "rtsp-camera.service")
        _systemctl("restart", rtsp)
    return jsonify(cfg)


@app.route("/api/camera/fps", methods=["POST"])
def api_camera_fps():
    """HTTP endpoint: set camera FPS and apply exposure/gain + restart RTSP.

    Inputs:
        POST JSON/form containing `value` or `fps` (integer).
    Output:
        JSON updated camera config dict.
    Transformation:
        Updates `fps` in camera config file, applies exposure/gain through I2C (if supported),
        and restarts the RTSP camera service.
    """
    cfg = load_camera_config()
    data = request.get_json(silent=True) or {}
    try:
        val = int(data.get("value", data.get("fps", cfg.get("fps", 5))))
    except (ValueError, TypeError):
        val = cfg.get("fps", 5)
    cfg["fps"] = val
    save_camera_config(cfg)
    _apply_exposure_gain(cfg)
    env = _get_env()
    rtsp = env.get("services", {}).get("rtsp_camera", "rtsp-camera.service")
    _systemctl("restart", rtsp)
    return jsonify(cfg)


@app.route("/api/camera/shutter", methods=["POST"])
def api_camera_shutter():
    """HTTP endpoint: set camera shutter (exposure time) and apply live via I2C.

    Inputs:
        POST JSON/form containing `value` or `shutter` (integer microseconds).
    Output:
        JSON updated camera config dict.
    Transformation:
        Updates `shutter` in camera config file, applies exposure/gain through I2C.
    """
    cfg = load_camera_config()
    data = request.get_json(silent=True) or {}
    try:
        val = int(data.get("value", data.get("shutter", cfg.get("shutter", 0))))
    except (ValueError, TypeError):
        val = cfg.get("shutter", 0)
    cfg["shutter"] = val
    cfg["fps"] = _fps_from_shutter_us(val if val > 0 else 1_000_000)
    save_camera_config(cfg)
    _apply_exposure_gain(cfg)
    return jsonify(cfg)


@app.route("/api/camera/gain", methods=["POST"])
def api_camera_gain():
    """HTTP endpoint: set camera gain and apply live via I2C.

    Inputs:
        POST JSON/form containing `value` or `gain` (float dB).
    Output:
        JSON updated camera config dict.
    Transformation:
        Updates `gain` in camera config file and applies exposure/gain through I2C.
    """
    cfg = load_camera_config()
    data = request.get_json(silent=True) or {}
    try:
        val = float(data.get("value", data.get("gain", cfg.get("gain", 0))))
    except (ValueError, TypeError):
        val = cfg.get("gain", 0)
    cfg["gain"] = val
    save_camera_config(cfg)
    _apply_exposure_gain(cfg)
    return jsonify(cfg)


@app.route("/api/camera/pixel_format", methods=["POST"])
def api_camera_pixel_format():
    """HTTP endpoint: set camera pixel format/bit depth and restart RTSP.

    Inputs:
        POST JSON/form containing `value` (case-insensitive; accepts "8"/"10" or "Y8"/"Y10"/"Y10P").
    Output:
        JSON updated camera config dict.
    Transformation:
        Normalizes `pixel_format` to one of `Y8`, `Y10`, `Y10P`, writes camera config,
        and restarts the RTSP camera service.
    """
    cfg = load_camera_config()
    data = request.get_json(silent=True) or {}
    val = str(data.get("value", data.get("pixel_format", "Y8"))).upper()
    if val in ("8", "8BIT"):
        val = "Y8"
    elif val in ("10", "10BIT"):
        val = "Y10"
    if val in ("Y8", "Y10", "Y10P"):
        cfg["pixel_format"] = val
        save_camera_config(cfg)
        env = _get_env()
        rtsp = env.get("services", {}).get("rtsp_camera", "rtsp-camera.service")
        _systemctl("restart", rtsp)
    return jsonify(cfg)


# --- Config API (WiFi, MQTT) - placeholder for task 5 ---


@app.route("/api/config/wifi", methods=["GET", "POST"])
def api_config_wifi():
    """HTTP endpoint: save or retrieve WiFi credentials for STA mode.

    Inputs:
        GET: none; returns sta_config_path + current SSID read from `wifi_credentials.conf`.
        POST: JSON/form containing:
            - `ssid` (required)
            - `password` (string)
    Output:
        POST success: {"status": "saved", "path": "<project-local wifi_credentials.conf>"}.
        POST error: {"error": "..."} with HTTP 400/500.
        GET: {"sta_config_path": "...", "ssid": "<current ssid or ''>"}.
    Transformation:
        Builds a wpa_supplicant `wifi_credentials.conf` block and writes it to project-local
        `wifi_credentials.conf`. If currently in STA mode (AP flag absent), attempts to apply
        it immediately by running `install/apply_wifi_credentials.sh` with `ENV_CONFIG` pointing
        to the project env config.
    """
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
            # Write to project-local file; bootstrap copies at STA boot
            project_dir = Path(env.get("paths", {}).get("home", "/home/raspberry"))
            local_path = project_dir / "wifi_credentials.conf"
            local_path.write_text(content, encoding="utf-8")
            # If in STA mode, apply immediately (copy to system path, restart wpa_supplicant)
            _project_root = Path(__file__).resolve().parent.parent.parent
            apply_script = _project_root / "install" / "apply_wifi_credentials.sh"
            if not (Path("/run/spectrometer-ap-enabled").exists()) and apply_script.is_file():
                try:
                    subprocess.run(
                        ["sudo", str(apply_script)],
                        check=False,
                        capture_output=True,
                        timeout=10,
                        env={**os.environ, "ENV_CONFIG": str(_project_root / "env_config.json")},
                    )
                except Exception:
                    pass
            return jsonify({"status": "saved", "path": str(local_path)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    # GET: return current SSID from wifi_credentials.conf (for form display; password never returned)
    ssid = ""
    project_dir = Path(env.get("paths", {}).get("home", "/home/raspberry"))
    creds_path = project_dir / "wifi_credentials.conf"
    if creds_path.is_file():
        try:
            for line in creds_path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("ssid="):
                    ssid = line.split("=", 1)[1].strip().strip('"')
                    break
        except Exception:
            pass
    return jsonify({"sta_config_path": sta_path, "ssid": ssid})


@app.route("/api/config/mqtt", methods=["GET", "POST"])
def api_config_mqtt():
    """HTTP endpoint: get or set MQTT connection parameters stored in env config.

    Inputs:
        GET: none.
        POST: JSON body with optional fields:
            broker (string), port (int), user (string), pass (string),
            cmd_topic (string), state_topic (string).
    Output:
        GET: JSON containing broker/port/user/cmd_topic/state_topic (strings/ints).
        POST success: {"status": "saved"}.
        POST error: {"error": "..."} with HTTP 500.
    Transformation:
        Reads/writes `DEFAULT_ENV_CONFIG` JSON file, updating the `mqtt` section.
    """
    env_path = DEFAULT_ENV_CONFIG
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


@app.route("/api/system/reboot", methods=["POST"])
def api_system_reboot():
    """HTTP endpoint: reboot the device via sudo.

    Inputs:
        POST request body (ignored).
    Output:
        On success: {"status": "rebooting"}.
        On failure: {"error": "..."} with HTTP 500.
    Transformation:
        Spawns `sudo reboot` as a detached process.
    """
    try:
        subprocess.Popen(["sudo", "reboot"], start_new_session=True)
        return jsonify({"status": "rebooting"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/system/shutdown", methods=["POST"])
def api_system_shutdown():
    """HTTP endpoint: shutdown the device via sudo.

    Inputs:
        POST request body (ignored).
    Output:
        On success: {"status": "shutting down"}.
        On failure: {"error": "..."} with HTTP 500.
    Transformation:
        Spawns `sudo shutdown -h now` as a detached process.
    """
    try:
        subprocess.Popen(["sudo", "shutdown", "-h", "now"], start_new_session=True)
        return jsonify({"status": "shutting down"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- Static / index ---


@app.route("/")
def index():
    """HTTP endpoint: serve the spectrometer web UI entry page.

    Inputs:
        GET /.
    Output:
        The `index.html` file from the configured `_STATIC_DIR`.
    Transformation:
        None; static file serving only.
    """
    return send_from_directory(_STATIC_DIR, "index.html")


def main():
    """Start the Flask webserver and the background capture thread.

    Inputs:
        None (configuration is loaded from environment via `_get_env()`).
    Output:
        None (runs a server loop).
    Transformation:
        Spawns `_capture_loop` thread as a daemon, reads `webserver.host/port`,
        and runs `app.run(...)`.
    """
    t = threading.Thread(target=_capture_loop, daemon=True)
    t.start()

    env = _get_env()
    ws = env.get("webserver", {}) or {}
    host = ws.get("host", "0.0.0.0")
    port = int(ws.get("port", 8080))
    app.run(host=host, port=port, threaded=True)


if __name__ == "__main__":
    main()
