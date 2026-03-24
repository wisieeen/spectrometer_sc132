"""
Shared env_config.json and camera_config.json loading.
Centralizes default paths used across spectrometer scripts.
"""
import json
import os

# Project root: parent of spectrometer package (resolves to repo root)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Centralized default paths (relative to project root)
DEFAULT_ENV_CONFIG = os.environ.get("ENV_CONFIG", os.path.join(_PROJECT_ROOT, "env_config.json"))
DEFAULT_CAMERA_CONFIG = os.path.join(_PROJECT_ROOT, "camera_config.json")


def load_env(path=None):
    """Load env_config.json. Uses path or ENV_CONFIG env / default."""
    p = path or DEFAULT_ENV_CONFIG
    with open(p) as f:
        env = json.load(f)
    if not isinstance(env, dict):
        raise ValueError("env_config must be a JSON object (dict)")
    return env


def _get_camera_config_path(env=None):
    """Resolve camera_config path from env or default."""
    if env is None:
        env = load_env()
    cfg_path = env.get("paths", {}).get("camera_config", DEFAULT_CAMERA_CONFIG)
    if not isinstance(cfg_path, str) or not cfg_path.strip():
        cfg_path = DEFAULT_CAMERA_CONFIG
    return cfg_path


def load_camera_config(env=None):
    """
    Load camera_config.json.
    If env is provided, reads path from env['paths']['camera_config'].
    Otherwise loads env first, then camera config.
    """
    cfg_path = _get_camera_config_path(env)
    with open(cfg_path) as f:
        cfg = json.load(f)
    if not isinstance(cfg, dict):
        raise ValueError("camera_config must be a JSON object (dict)")
    return cfg


def save_camera_config(cfg, env=None):
    """Save camera_config.json. Uses same path resolution as load_camera_config."""
    cfg_path = _get_camera_config_path(env)
    with open(cfg_path, "w") as f:
        json.dump(cfg, f, indent=2)
