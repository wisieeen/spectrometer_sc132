"""
Shared env_config.json and camera_config.json loading.
Centralizes default paths used across spectrometer scripts.
"""
import json
import os

# Centralized default paths
DEFAULT_ENV_CONFIG = os.environ.get("ENV_CONFIG", "/home/raspberry/env_config.json")
DEFAULT_CAMERA_CONFIG = "/home/raspberry/camera_config.json"


def load_env(path=None):
    """Load env_config.json. Uses path or ENV_CONFIG env / default."""
    p = path or DEFAULT_ENV_CONFIG
    with open(p) as f:
        env = json.load(f)
    if not isinstance(env, dict):
        raise ValueError("env_config must be a JSON object (dict)")
    return env


def load_camera_config(env=None):
    """
    Load camera_config.json.
    If env is provided, reads path from env['paths']['camera_config'].
    Otherwise loads env first, then camera config.
    """
    if env is None:
        env = load_env()
    cfg_path = env.get("paths", {}).get("camera_config", DEFAULT_CAMERA_CONFIG)
    if not isinstance(cfg_path, str) or not cfg_path.strip():
        cfg_path = DEFAULT_CAMERA_CONFIG
    with open(cfg_path) as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        raise ValueError("camera_config must be a JSON object (dict)")
    return cfg
