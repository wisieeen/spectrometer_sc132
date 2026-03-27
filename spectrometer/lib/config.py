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
    try:
        with open(path) as f:
            cfg = json.load(f)
    except json.JSONDecodeError as e:
        raise json.JSONDecodeError(
            f"{e.msg} (file: {path})",
            e.doc,
            e.pos,
        ) from e
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


def get_processing_cfg(spec_cfg=None):
    """
    Extract and validate processing settings from spectrometer config.
    Returns dict: frame_average_n, dark_flat_enabled, dark_frame_path, flat_frame_path,
    richardson_lucy_enabled, richardson_lucy_psf_sigma, richardson_lucy_psf_path, richardson_lucy_iterations.
    """
    if spec_cfg is None:
        spec_cfg = load_spectrometer_config()
    proc = spec_cfg.get("processing", {}) or {}
    try:
        frame_average_n = max(1, min(1000, int(proc.get("frame_average_n", 1))))
    except (TypeError, ValueError):
        frame_average_n = 1
    try:
        richardson_lucy_iterations = max(1, min(100, int(proc.get("richardson_lucy_iterations", 15))))
    except (TypeError, ValueError):
        richardson_lucy_iterations = 15
    try:
        richardson_lucy_psf_sigma = max(0.5, min(20.0, float(proc.get("richardson_lucy_psf_sigma", 3.0))))
    except (TypeError, ValueError):
        richardson_lucy_psf_sigma = 3.0
    richardson_lucy_psf_path = (proc.get("richardson_lucy_psf_path") or "").strip() or None
    return {
        "frame_average_n": frame_average_n,
        "dark_flat_enabled": bool(proc.get("dark_flat_enabled", False)),
        "dark_frame_path": proc.get("dark_frame_path") or None,
        "flat_frame_path": proc.get("flat_frame_path") or None,
        "richardson_lucy_enabled": bool(proc.get("richardson_lucy_enabled", False)),
        "richardson_lucy_psf_sigma": richardson_lucy_psf_sigma,
        "richardson_lucy_psf_path": richardson_lucy_psf_path,
        "richardson_lucy_iterations": richardson_lucy_iterations,
    }
