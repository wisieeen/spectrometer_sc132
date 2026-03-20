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
from scripts.camera_capture import capture_frame, capture_frames_averaged


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


def _acquire_frame(spec_cfg, dark, flat):
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

    if n > 1:
        frame = capture_frames_averaged(n)
    else:
        frame = capture_frame()
        frame = frame.astype(np.float64)

    if proc["dark_flat_enabled"] and (dark is not None or flat is not None):
        frame = apply_dark_flat_frame(frame, dark, flat)

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

        proc = get_processing_cfg(spec_cfg)
        if proc["richardson_lucy_enabled"]:
            intensities = richardson_lucy_deconvolve(
                intensities,
                psf_sigma_px=proc["richardson_lucy_psf_sigma"],
                num_iterations=proc["richardson_lucy_iterations"],
                psf_path=proc.get("richardson_lucy_psf_path"),
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
            spec_cfg = load_spectrometer_config()
            proc = get_processing_cfg(spec_cfg)
            dark, flat = load_dark_flat(proc["dark_frame_path"], proc["flat_frame_path"])
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
            if running:
                client.publish(st + "/status", "running", retain=True)
                spec_cfg = load_spectrometer_config()
                proc = get_processing_cfg(spec_cfg)
                dark, flat = load_dark_flat(proc["dark_frame_path"], proc["flat_frame_path"])
                frame = _acquire_frame(spec_cfg, dark, flat)
                pm = {
                    "frame_average_n": proc["frame_average_n"],
                    "dark_flat_applied": proc["dark_flat_enabled"] and (dark is not None or flat is not None),
                    "richardson_lucy_applied": proc["richardson_lucy_enabled"],
                }
                _process_frame(frame, spec_cfg, output, pm, dark=dark)
            else:
                client.publish(st + "/status", "idle", retain=True)
            time.sleep(interval_ms / 1000.0)
    except KeyboardInterrupt:
        pass
    client.loop_stop()


if __name__ == "__main__":
    main()
