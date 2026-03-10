"""
Load/save spectrometer_config.json.
Reads spectrometer config path from env_config.json (spectrometer.config_path).
"""
import json
import os

from .env_config import DEFAULT_ENV_CONFIG
DEFAULT_SPECTROMETER_CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "spectrometer_config.json"
)


def _get_spectrometer_config_path():
    try:
        with open(DEFAULT_ENV_CONFIG) as f:
            env = json.load(f)
        return env.get("spectrometer", {}).get("config_path", DEFAULT_SPECTROMETER_CONFIG)
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return DEFAULT_SPECTROMETER_CONFIG


def load_spectrometer_config(path=None):
    path = path or _get_spectrometer_config_path()
    with open(path) as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        cfg = {}
    cfg.setdefault("channels", [])
    cfg.setdefault("calibrations", [])
    cfg.setdefault("processing", {})
    return cfg


def save_spectrometer_config(cfg, path=None):
    path = path or _get_spectrometer_config_path()
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
