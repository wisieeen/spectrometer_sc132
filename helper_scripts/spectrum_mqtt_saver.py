#!/usr/bin/env python3
"""
Subscribes to spectrum MQTT topic and saves each spectrum as CSV in spectra/ folder.
Format: wavelength,intensity per line.
Filename: spectrum_{channel_id}_{YYYYMMDD_HHMMSS}.csv (ASCII time).
Uses env_config.json for MQTT credentials; spectrum_saver_config.json for topic and spectra_dir.
"""
import argparse
import json
import os
import sys
from datetime import datetime

import paho.mqtt.client as mqtt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.env_config import DEFAULT_ENV_CONFIG, load_env

DEFAULT_CONFIG = "spectrum_saver_config.json"


def _load_config(path):
    """Load a JSON config file from disk.

    Inputs:
        path: File system path to a JSON file.
    Output:
        Parsed JSON object (typically a dict).
    Transformation:
        Reads the file and deserializes it with `json.load`.
    """
    with open(path) as f:
        return json.load(f)


def _find_config(config_path):
    """Resolve the spectrum saver config file path.

    Inputs:
        config_path: Optional explicit config file path.
    Output:
        Absolute/relative path string to the config file, or None if not found.
    Transformation:
        If `config_path` exists, returns it; otherwise searches in the current working directory
        and next to this script for `DEFAULT_CONFIG`.
    """
    if config_path and os.path.isfile(config_path):
        return config_path
    for base in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        p = os.path.join(base, DEFAULT_CONFIG)
        if os.path.isfile(p):
            return p
    return None


def _get_mqtt_config(cfg):
    """MQTT from env_config; spectrum_saver_config mqtt overrides if present."""
    try:
        env = load_env()
        mq = dict(env.get("mqtt", {}))
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        mq = {}
    mq.update(cfg.get("mqtt", {}))
    return mq


def main():
    """CLI entrypoint: subscribe to spectrum MQTT and save messages as CSV files.

    Inputs:
        Command-line args:
        - `--config` / `-c`: optional path to `spectrum_saver_config.json`
        - `--spectra-dir` / `-o`: optional output directory for CSV files
    Output:
        Writes `spectrum_<channel_id>_<timestamp>.csv` into the configured spectra directory
        and runs an MQTT loop until interrupted.
    Transformation:
        Loads saver config, merges MQTT credentials from env config, connects to the broker,
        subscribes to the configured topic, and for each received spectrum message writes a CSV.
    """
    parser = argparse.ArgumentParser(description="Save spectrum MQTT messages to CSV")
    parser.add_argument("--config", "-c", help="Path to spectrum_saver_config.json")
    parser.add_argument("--spectra-dir", "-o", help="Output directory (default: spectra/ in config dir)")
    args = parser.parse_args()

    config_path = _find_config(args.config)
    if not config_path:
        print(f"Config not found. Create {DEFAULT_CONFIG} with topic, spectra_dir. MQTT from {DEFAULT_ENV_CONFIG}.", file=sys.stderr)
        sys.exit(1)

    cfg = _load_config(config_path)
    mq = _get_mqtt_config(cfg)
    if not mq.get("broker"):
        print(f"MQTT broker required. Set in {DEFAULT_ENV_CONFIG} or {DEFAULT_CONFIG} mqtt.broker.", file=sys.stderr)
        sys.exit(1)
    topic = cfg.get("topic", "lab/spectrometer/state/spectrum/#")
    spectra_dir = args.spectra_dir or cfg.get("spectra_dir", "spectra")
    if not os.path.isabs(spectra_dir):
        spectra_dir = os.path.join(os.path.dirname(config_path), spectra_dir)

    def on_message(client, userdata, msg):
        """MQTT callback: parse spectrum payload and append it as a CSV file.

        Inputs:
            client: MQTT client instance.
            userdata: Unused callback userdata.
            msg: MQTT message containing JSON payload with spectrum fields.
        Output:
            None (side-effect: writes a CSV file to disk).
        Transformation:
            - Parses JSON payload and validates `wavelengths_nm` + `intensities` lengths.
            - Extracts `channel_id` and `timestamp` (ISO-8601, optional) for filename generation.
            - Writes CSV with header `wavelength,intensity` and one line per sample.
        """
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        w = payload.get("wavelengths_nm")
        i = payload.get("intensities")
        if not w or not i or len(w) != len(i):
            return
        channel_id = payload.get("channel_id", "ch0")
        ts = payload.get("timestamp")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                dt = dt.astimezone()
            except (ValueError, TypeError):
                dt = datetime.now()
        else:
            dt = datetime.now()
        ascii_time = dt.strftime("%Y%m%d_%H%M%S") + f"_{dt.microsecond // 1000:03d}"
        os.makedirs(spectra_dir, exist_ok=True)
        filename = f"spectrum_{channel_id}_{ascii_time}.csv"
        path = os.path.join(spectra_dir, filename)
        with open(path, "w") as f:
            f.write("wavelength,intensity\n")
            for idx in range(len(w)):
                f.write(f"{w[idx]},{i[idx]}\n")
        print(f"Saved {path}")

    client = mqtt.Client()
    client.username_pw_set(mq.get("user", ""), mq.get("pass", ""))
    client.on_message = on_message
    client.connect(mq["broker"], int(mq.get("port", 1883)), 60)
    client.subscribe(topic)
    print(f"Subscribed to {topic}, saving to {os.path.abspath(spectra_dir)}/")
    client.loop_forever()


if __name__ == "__main__":
    main()
