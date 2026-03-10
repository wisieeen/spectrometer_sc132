#!/usr/bin/env python3
"""
Main spectrometer service. Captures frames, extracts spectra, publishes via output adapter.
Prerequisite: RTSP stream OFF.
MQTT commands: start, stop (continuous), single (on-demand), interval_ms,
  processing_frame_average_n, processing_dark_flat_enabled,
  processing_wiener_enabled, processing_wiener_psf_sigma, processing_wiener_regularization.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import numpy as np
import paho.mqtt.client as mqtt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.config import load_spectrometer_config, save_spectrometer_config
from lib.env_config import load_env, load_camera_config
from lib.spectrum import extract_line_profile, fit_calibration, compute_spectrum
from lib.output.mqtt_adapter import MQTTAdapter
from lib.signal_processing import apply_dark_flat_frame, load_dark_flat, wiener_deconvolve
from scripts.camera_capture import capture_frame, capture_frames_averaged


def _get_output_adapter(env=None):
    env = env or load_env()
    mq = env.get("mqtt", {})
    return MQTTAdapter(
        broker=mq["broker"],
        port=int(mq["port"]),
        user=mq["user"],
        password=mq["pass"],
        state_topic=env.get("spectrometer", {}).get("state_topic", "lab/spectrometer/state/"),
    )


def _get_processing_cfg(spec_cfg):
    """Extract processing settings from spectrometer config."""
    proc = spec_cfg.get("processing", {}) or {}
    try:
        frame_average_n = int(proc.get("frame_average_n", 1))
    except (TypeError, ValueError):
        frame_average_n = 1
    frame_average_n = max(1, min(1000, frame_average_n))

    try:
        wiener_psf_sigma = float(proc.get("wiener_psf_sigma", 3.0))
    except (TypeError, ValueError):
        wiener_psf_sigma = 3.0
    wiener_psf_sigma = max(0.5, min(20.0, wiener_psf_sigma))

    try:
        wiener_regularization = float(proc.get("wiener_regularization", 0.01))
    except (TypeError, ValueError):
        wiener_regularization = 0.01
    wiener_regularization = max(0.0001, min(1.0, wiener_regularization))

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
    """
    Capture and optionally process frame(s).
    Applies frame averaging first, then dark/flat correction if enabled.
    """
    proc = _get_processing_cfg(spec_cfg)
    n = max(1, proc["frame_average_n"])

    if n > 1:
        frame = capture_frames_averaged(n)
    else:
        frame = capture_frame()
        frame = frame.astype(np.float64)

    if proc["dark_flat_enabled"] and (dark is not None or flat is not None):
        frame = apply_dark_flat_frame(frame, dark, flat)

    return frame


def _process_frame(frame, spec_cfg, output, processing_meta=None):
    cam_cfg = load_camera_config()
    meta = {
        "shutter_us": cam_cfg.get("shutter"),
        "gain_db": cam_cfg.get("gain"),
    }
    if processing_meta:
        meta["processing"] = processing_meta

    calibrations = {c["id"]: c for c in spec_cfg.get("calibrations", []) if isinstance(c, dict) and isinstance(c.get("id"), str)}

    for ch in spec_cfg.get("channels", []):
        if not isinstance(ch, dict) or "id" not in ch:
            continue
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

        intensities = extract_line_profile(frame, start, end, thickness)
        if len(intensities) == 0:
            continue

        proc = _get_processing_cfg(spec_cfg)
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
            coeffs = np.array([1.0, 0.0])  # pixel = wavelength fallback

        wavelengths, ints = compute_spectrum(intensities, coeffs)

        spectrum = {
            "channel_id": ch["id"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "wavelengths_nm": wavelengths.tolist(),
            "intensities": ints.tolist(),
            "meta": meta,
        }
        output.send_spectrum(spectrum)


def main():
    env = load_env()
    spec_cfg = load_spectrometer_config()
    output = _get_output_adapter(env)

    cmd_topic = env.get("spectrometer", {}).get("cmd_topic", "lab/spectrometer/cmd/")
    state_topic = env.get("spectrometer", {}).get("state_topic", "lab/spectrometer/state/")
    cmd_topic = cmd_topic.rstrip("/") + "/"
    st = state_topic.rstrip("/")

    running = False
    interval_ms = 1000

    def _publish_processing_state(client):
        proc = _get_processing_cfg(load_spectrometer_config())
        client.publish(st + "/processing_frame_average_n", str(proc["frame_average_n"]), retain=True)
        client.publish(
            st + "/processing_dark_flat_enabled",
            "true" if proc["dark_flat_enabled"] else "false",
            retain=True,
        )
        client.publish(st + "/processing_wiener_enabled", "true" if proc["wiener_enabled"] else "false", retain=True)
        client.publish(st + "/processing_wiener_psf_sigma", str(proc["wiener_psf_sigma"]), retain=True)
        client.publish(st + "/processing_wiener_regularization", str(proc["wiener_regularization"]), retain=True)

    def on_message(client, userdata, msg):
        nonlocal running, interval_ms, spec_cfg
        payload = msg.payload.decode().strip()
        topic = msg.topic.replace(cmd_topic, "")

        if topic == "start":
            running = True
        elif topic == "stop":
            running = False
        elif topic == "continuous":
            running = payload.upper() in ("ON", "1", "TRUE", "YES")
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
        elif topic == "processing_wiener_enabled":
            enabled = payload.lower() in ("true", "1", "on", "yes")
            spec_cfg = load_spectrometer_config()
            proc = spec_cfg.setdefault("processing", {})
            proc["wiener_enabled"] = enabled
            save_spectrometer_config(spec_cfg)
            client.publish(st + "/processing_wiener_enabled", "true" if enabled else "false", retain=True)
        elif topic == "processing_wiener_psf_sigma":
            try:
                val = max(0.5, min(20.0, float(payload)))
            except (ValueError, TypeError):
                val = 3.0
            spec_cfg = load_spectrometer_config()
            proc = spec_cfg.setdefault("processing", {})
            proc["wiener_psf_sigma"] = val
            save_spectrometer_config(spec_cfg)
            client.publish(st + "/processing_wiener_psf_sigma", str(val), retain=True)
        elif topic == "processing_wiener_regularization":
            try:
                val = max(0.0001, min(1.0, float(payload)))
            except (ValueError, TypeError):
                val = 0.01
            spec_cfg = load_spectrometer_config()
            proc = spec_cfg.setdefault("processing", {})
            proc["wiener_regularization"] = val
            save_spectrometer_config(spec_cfg)
            client.publish(st + "/processing_wiener_regularization", str(val), retain=True)
        elif topic == "single":
            spec_cfg = load_spectrometer_config()
            proc = _get_processing_cfg(spec_cfg)
            dark, flat = load_dark_flat(proc["dark_frame_path"], proc["flat_frame_path"])
            frame = _acquire_frame(spec_cfg, dark, flat)
            pm = {
                "frame_average_n": proc["frame_average_n"],
                "dark_flat_applied": proc["dark_flat_enabled"] and (dark is not None or flat is not None),
                "wiener_applied": proc["wiener_enabled"],
            }
            _process_frame(frame, spec_cfg, output, pm)
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
            if running:
                client.publish(st + "/status", "running", retain=True)
                spec_cfg = load_spectrometer_config()
                proc = _get_processing_cfg(spec_cfg)
                dark, flat = load_dark_flat(proc["dark_frame_path"], proc["flat_frame_path"])
                frame = _acquire_frame(spec_cfg, dark, flat)
                pm = {
                    "frame_average_n": proc["frame_average_n"],
                    "dark_flat_applied": proc["dark_flat_enabled"] and (dark is not None or flat is not None),
                    "wiener_applied": proc["wiener_enabled"],
                }
                _process_frame(frame, spec_cfg, output, pm)
            else:
                client.publish(st + "/status", "idle", retain=True)
            time.sleep(interval_ms / 1000.0)
    except KeyboardInterrupt:
        pass
    client.loop_stop()


if __name__ == "__main__":
    main()
