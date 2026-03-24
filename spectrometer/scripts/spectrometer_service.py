#!/usr/bin/env python3
"""
Main spectrometer service. Captures frames, extracts spectra, publishes via output adapter.
Prerequisite: RTSP stream OFF.
MQTT commands: start, stop (continuous), single (on-demand), interval_ms,
  processing_frame_average_n, processing_dark_flat_enabled,
  processing_richardson_lucy_enabled, processing_richardson_lucy_psf_sigma, processing_richardson_lucy_iterations.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import paho.mqtt.client as mqtt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.config import load_spectrometer_config, save_spectrometer_config, get_processing_cfg
from lib.env_config import load_env, load_camera_config
from lib.spectrum import extract_line_profile, fit_calibration, compute_spectrum
from lib.output.mqtt_adapter import MQTTAdapter
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


def _get_output_adapter(env=None):
    """Create and configure the MQTT output adapter.

    Inputs:
        env: Optional environment configuration dict. If not provided, `load_env()` is used.
    Output:
        MQTTAdapter instance configured with broker credentials and spectrometer state topic.
    Transformation:
        Reads `env["mqtt"]` for connection parameters and derives the state-topic prefix from
        `env["spectrometer"]["state_topic"]` (defaulting to `lab/spectrometer/state/`),
        then instantiates `MQTTAdapter`.
    """
    env = env or load_env()
    mq = env.get("mqtt", {})
    return MQTTAdapter(
        broker=mq["broker"],
        port=int(mq["port"]),
        user=mq["user"],
        password=mq["pass"],
        state_topic=env.get("spectrometer", {}).get("state_topic", "lab/spectrometer/state/"),
    )


def _acquire_frame(spec_cfg, dark, flat, timing_rows=None):
    """Capture spectrometer frame(s) and optionally apply dark/flat correction.

    Inputs:
        spec_cfg: Spectrometer configuration dict (used to read `processing` settings).
        dark: Dark correction frame array (or None).
        flat: Flat correction frame array (or None).
    Output:
        A floating-point 2D frame array (NumPy).
    Transformation:
        Captures either a single frame or `processing.frame_average_n` frames, averages them
        when needed, casts to float, then applies `apply_dark_flat_frame` only if enabled and
        both correction data are available.
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


def _process_frame(frame, spec_cfg, output, processing_meta=None, dark=None):
    """Extract spectra from a frame and publish them via the output adapter.

    Inputs:
        frame: Captured frame array (2D) to analyze.
        spec_cfg: Spectrometer configuration dict including `channels` and `calibrations`.
        output: Output adapter (expects `send_spectrum(spectrum_dict)`).
        processing_meta: Optional dict describing which processing steps were applied.
        dark: Dark frame array (or None). Used only as a signal/flag (no correction here).
    Output:
        None (publishes spectra as a side-effect).
    Transformation:
        For each configured channel:
        - extracts a line profile from the channel ROI,
        - optionally deconvolves with Richardson–Lucy,
        - converts pixel positions to wavelengths using either calibration coefficients
          or fitted calibration pairs,
        - builds a spectrum dict with timestamp + metadata and publishes it.
    """
    timing = processing_meta.get("_timing") if isinstance(processing_meta, dict) else None
    processing_meta_public = None
    if isinstance(processing_meta, dict):
        processing_meta_public = {k: v for k, v in processing_meta.items() if k != "_timing"}

    cam_cfg = load_camera_config()
    meta = {
        "shutter_us": cam_cfg.get("shutter"),
        "gain_db": cam_cfg.get("gain"),
    }
    if processing_meta_public:
        meta["processing"] = processing_meta_public

    calibrations = {c["id"]: c for c in spec_cfg.get("calibrations", []) if isinstance(c, dict) and isinstance(c.get("id"), str)}

    for ch in spec_cfg.get("channels", []):
        if not isinstance(ch, dict) or "id" not in ch:
            continue
        ch_id = ch.get("id", "")
        line = ch.get("line")
        if not line or "start" not in line or "end" not in line:
            continue
        start_seq, end_seq = line["start"], line["end"]
        if not (isinstance(start_seq, (list, tuple)) and len(start_seq) >= 2 and
                isinstance(end_seq, (list, tuple)) and len(end_seq) >= 2):
            continue
        try:
            start = (int(start_seq[0]), int(start_seq[1]))
            end = (int(end_seq[0]), int(end_seq[1]))
        except (TypeError, ValueError, IndexError):
            continue
        try:
            thickness = max(1, min(100, int(line.get("thickness", 5))))
        except (TypeError, ValueError):
            thickness = 5
        cal_id = ch.get("calibration_id", "default")
        cal = calibrations.get(cal_id)

        t0 = time.perf_counter_ns()
        intensities = extract_line_profile(frame, start, end, thickness)
        if timing is not None:
            timing.append(
                {
                    "step": "extract_line_profile",
                    "channel_id": ch_id,
                    "duration_ms": (time.perf_counter_ns() - t0) / 1_000_000.0,
                }
            )
        if len(intensities) == 0:
            continue

        proc = get_processing_cfg(spec_cfg)
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
                        "channel_id": ch_id,
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
            coeffs = np.array([1.0, 0.0])  # pixel = wavelength fallback
        if timing is not None:
            timing.append(
                {
                    "step": "compute_calibration_coeffs",
                    "channel_id": ch_id,
                    "duration_ms": (time.perf_counter_ns() - t0) / 1_000_000.0,
                }
            )

        t0 = time.perf_counter_ns()
        wavelengths, ints = compute_spectrum(intensities, coeffs)
        if timing is not None:
            timing.append(
                {
                    "step": "compute_spectrum",
                    "channel_id": ch_id,
                    "duration_ms": (time.perf_counter_ns() - t0) / 1_000_000.0,
                }
            )

        spectrum = {
            "channel_id": ch["id"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "wavelengths_nm": wavelengths.tolist(),
            "intensities": ints.tolist(),
            "meta": meta,
        }
        t0 = time.perf_counter_ns()
        output.send_spectrum(spectrum)
        if timing is not None:
            timing.append(
                {
                    "step": "output.send_spectrum",
                    "channel_id": ch_id,
                    "duration_ms": (time.perf_counter_ns() - t0) / 1_000_000.0,
                }
            )


def main():
    """Run the spectrometer service with MQTT control.

    Inputs:
        None (configuration is loaded from environment/disk via helper functions).
    Output:
        None (runs until interrupted; publishes spectra and processing state continuously).
    Transformation:
        - Initializes MQTT client and subscribes to command topic.
        - When `running` is enabled, repeatedly captures frames, converts them into spectra,
          and publishes spectra.
        - Handles MQTT commands to start/stop, adjust interval, adjust processing settings,
          and perform single-shot captures.
    """
    env = load_env()
    spec_cfg = load_spectrometer_config()
    output = _get_output_adapter(env)

    cmd_topic = env.get("spectrometer", {}).get("cmd_topic", "lab/spectrometer/cmd/")
    state_topic = env.get("spectrometer", {}).get("state_topic", "lab/spectrometer/state/")
    cmd_topic = cmd_topic.rstrip("/") + "/"
    st = state_topic.rstrip("/")

    running = False
    interval_ms = 1000
    timing_enabled = _is_timing_enabled(env)
    timing_path = _timing_log_path(env)
    cycle_id = 0
    force_dark_flat_reload = True
    dark_flat_cache = {
        "dark": None,
        "flat": None,
        "dark_path": None,
        "flat_path": None,
        "valid": False,
    }

    def _publish_processing_state(client):
        """Publish processing parameters as retained MQTT messages.

        Inputs:
            client: MQTT client instance (expects `publish(topic, payload, retain=...)`).
        Output:
            None.
        Transformation:
            Reads the current `processing` config from disk and publishes each processing field
            under the spectrometer state-topic prefix (`st`).
        """
        proc = get_processing_cfg(load_spectrometer_config())
        client.publish(st + "/processing_frame_average_n", str(proc["frame_average_n"]), retain=True)
        client.publish(
            st + "/processing_dark_flat_enabled",
            "true" if proc["dark_flat_enabled"] else "false",
            retain=True,
        )
        client.publish(
            st + "/processing_richardson_lucy_enabled",
            "true" if proc["richardson_lucy_enabled"] else "false",
            retain=True,
        )
        client.publish(st + "/processing_richardson_lucy_psf_sigma", str(proc["richardson_lucy_psf_sigma"]), retain=True)
        client.publish(st + "/processing_richardson_lucy_psf_path", proc.get("richardson_lucy_psf_path") or "", retain=True)
        client.publish(st + "/processing_richardson_lucy_iterations", str(proc["richardson_lucy_iterations"]), retain=True)

    def on_message(client, userdata, msg):
        """Handle incoming MQTT commands to control acquisition/processing.

        Inputs:
            client: MQTT client instance.
            userdata: Unused callback userdata.
            msg: MQTT message containing `msg.topic` and `msg.payload`.
        Output:
            None (updates runtime state and/or publishes responses to state topic).
        Transformation:
            - Derives the command by stripping `cmd_topic` from the MQTT topic.
            - Updates `running` / `interval_ms` based on `start/stop/continuous/interval_ms`.
            - Updates processing settings in the spectrometer config file.
            - For `single`, captures and processes one spectrum snapshot immediately.
            - For `preview`, spawns `spectrometer_preview.py` in a new process.
        """
        nonlocal running, interval_ms, spec_cfg, force_dark_flat_reload
        payload = msg.payload.decode().strip()
        topic = msg.topic.replace(cmd_topic, "")

        if topic == "start":
            running = True
            force_dark_flat_reload = True
            invalidate_capture_context_cache()
        elif topic == "stop":
            running = False
        elif topic == "continuous":
            running = payload.upper() in ("ON", "1", "TRUE", "YES")
            if running:
                force_dark_flat_reload = True
                invalidate_capture_context_cache()
        elif topic == "interval_ms":
            try:
                interval_ms = max(100, min(3600000, int(payload))) if payload else 1000
            except (ValueError, TypeError):
                interval_ms = 1000
            client.publish(st + "/interval_ms", str(interval_ms), retain=True)
        elif topic == "processing_frame_average_n":
            try:
                n = max(1, min(1000, int(payload))) if payload else 1
            except (ValueError, TypeError):
                n = 1
            spec_cfg = load_spectrometer_config()
            proc = spec_cfg.setdefault("processing", {})
            proc["frame_average_n"] = n
            save_spectrometer_config(spec_cfg)
            client.publish(st + "/processing_frame_average_n", str(n), retain=True)
        elif topic == "processing_dark_flat_enabled":
            enabled = payload.lower() in ("true", "1", "on", "yes")
            spec_cfg = load_spectrometer_config()
            proc = spec_cfg.setdefault("processing", {})
            proc["dark_flat_enabled"] = enabled
            save_spectrometer_config(spec_cfg)
            client.publish(st + "/processing_dark_flat_enabled", "true" if enabled else "false", retain=True)
        elif topic == "processing_richardson_lucy_enabled":
            enabled = payload.lower() in ("true", "1", "on", "yes")
            spec_cfg = load_spectrometer_config()
            proc = spec_cfg.setdefault("processing", {})
            proc["richardson_lucy_enabled"] = enabled
            save_spectrometer_config(spec_cfg)
            client.publish(st + "/processing_richardson_lucy_enabled", "true" if enabled else "false", retain=True)
        elif topic == "processing_richardson_lucy_psf_sigma":
            try:
                val = max(0.5, min(20.0, float(payload)))
            except (ValueError, TypeError):
                val = 3.0
            spec_cfg = load_spectrometer_config()
            proc = spec_cfg.setdefault("processing", {})
            proc["richardson_lucy_psf_sigma"] = val
            save_spectrometer_config(spec_cfg)
            client.publish(st + "/processing_richardson_lucy_psf_sigma", str(val), retain=True)
        elif topic == "processing_richardson_lucy_iterations":
            try:
                val = max(1, min(100, int(payload)))
            except (ValueError, TypeError):
                val = 15
            spec_cfg = load_spectrometer_config()
            proc = spec_cfg.setdefault("processing", {})
            proc["richardson_lucy_iterations"] = val
            save_spectrometer_config(spec_cfg)
            client.publish(st + "/processing_richardson_lucy_iterations", str(val), retain=True)
        elif topic == "processing_richardson_lucy_psf_path":
            path = (payload or "").strip() or None
            spec_cfg = load_spectrometer_config()
            proc = spec_cfg.setdefault("processing", {})
            proc["richardson_lucy_psf_path"] = path
            save_spectrometer_config(spec_cfg)
            client.publish(st + "/processing_richardson_lucy_psf_path", path or "", retain=True)
        elif topic == "single":
            force_dark_flat_reload = True
            invalidate_capture_context_cache()
            spec_cfg = load_spectrometer_config()
            proc = get_processing_cfg(spec_cfg)
            dark, flat, _ = _load_dark_flat_cached(proc, dark_flat_cache, force_reload=True)
            force_dark_flat_reload = False
            frame = _acquire_frame(spec_cfg, dark, flat)
            pm = {
                "frame_average_n": proc["frame_average_n"],
                "dark_flat_applied": proc["dark_flat_enabled"] and (dark is not None or flat is not None),
                "richardson_lucy_applied": proc["richardson_lucy_enabled"],
            }
            _process_frame(frame, spec_cfg, output, pm, dark=dark)
        elif topic == "preview":
            preview_script = os.path.join(os.path.dirname(__file__), "spectrometer_preview.py")
            subprocess.Popen(
                [sys.executable, preview_script],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                env=os.environ,
            )

    client = mqtt.Client()
    client.username_pw_set(env["mqtt"]["user"], env["mqtt"]["pass"])
    client.on_message = on_message
    client.connect(env["mqtt"]["broker"], int(env["mqtt"]["port"]), 60)
    client.subscribe(cmd_topic + "#")
    client.loop_start()

    client.publish(st + "/status", "idle", retain=True)
    client.publish(st + "/interval_ms", str(interval_ms), retain=True)
    _publish_processing_state(client)

    try:
        while True:
            cycle_start_ns = time.perf_counter_ns()
            if running:
                client.publish(st + "/status", "running", retain=True)
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
                    dark_flat_cache,
                    force_reload=force_dark_flat_reload,
                )
                force_dark_flat_reload = False
                if timing_enabled:
                    timing_rows.append({"step": "load_dark_flat", "channel_id": "", "duration_ms": (time.perf_counter_ns() - t0) / 1_000_000.0})
                    timing_rows.append({"step": "load_dark_flat_cache_miss" if cache_miss else "load_dark_flat_cache_hit", "channel_id": "", "duration_ms": 0.0})

                t0 = time.perf_counter_ns()
                frame = _acquire_frame(spec_cfg, dark, flat, timing_rows=timing_rows if timing_enabled else None)
                if timing_enabled:
                    timing_rows.append({"step": "_acquire_frame", "channel_id": "", "duration_ms": (time.perf_counter_ns() - t0) / 1_000_000.0})
                pm = {
                    "frame_average_n": proc["frame_average_n"],
                    "dark_flat_applied": proc["dark_flat_enabled"] and (dark is not None or flat is not None),
                    "richardson_lucy_applied": proc["richardson_lucy_enabled"],
                }
                if timing_enabled:
                    pm["_timing"] = timing_rows

                t0 = time.perf_counter_ns()
                _process_frame(frame, spec_cfg, output, pm, dark=dark)
                if timing_enabled:
                    timing_rows.append({"step": "_process_frame_total", "channel_id": "", "duration_ms": (time.perf_counter_ns() - t0) / 1_000_000.0})

                    cycle_id += 1
                    rows_common = {
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                        "cycle_id": cycle_id,
                        "interval_ms": interval_ms,
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
            else:
                client.publish(st + "/status", "idle", retain=True)
            sleep_s = interval_ms / 1000.0
            time.sleep(sleep_s)
            if timing_enabled and running:
                _append_timing_row(
                    timing_path,
                    {
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                        "cycle_id": cycle_id,
                        "step": "cycle_total_with_sleep",
                        "channel_id": "",
                        "duration_ms": (time.perf_counter_ns() - cycle_start_ns) / 1_000_000.0,
                        "interval_ms": interval_ms,
                        "frame_average_n": proc["frame_average_n"],
                        "dark_flat_enabled": str(proc["dark_flat_enabled"]).lower(),
                        "richardson_lucy_enabled": str(proc["richardson_lucy_enabled"]).lower(),
                        "channels_configured": len(spec_cfg.get("channels", [])),
                    },
                )
    except KeyboardInterrupt:
        pass
    client.loop_stop()


if __name__ == "__main__":
    main()
