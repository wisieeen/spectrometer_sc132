"""
Dark and flat-field correction: (raw - dark) / (flat - dark).
Removes fixed-pattern noise, vignetting, pixel-to-pixel sensitivity variation.
Independent module; no dependencies on other processing techniques.
"""
import os
import numpy as np


def load_dark_flat(dark_path: str | None, flat_path: str | None) -> tuple[np.ndarray | None, np.ndarray | None]:
    """
    Load dark and flat frames from .npy files.
    Returns (dark, flat). Either can be None if path is None or file missing.
    """
    dark = None
    if dark_path and os.path.isfile(dark_path):
        arr = np.load(dark_path)
        if isinstance(arr, np.ndarray) and arr.ndim == 2 and np.issubdtype(arr.dtype, np.number):
            dark = arr.astype(np.float64)

    flat = None
    if flat_path and os.path.isfile(flat_path):
        arr = np.load(flat_path)
        if isinstance(arr, np.ndarray) and arr.ndim == 2 and np.issubdtype(arr.dtype, np.number):
            flat = arr.astype(np.float64)

    return dark, flat


def apply_dark_flat_frame(
    frame: np.ndarray,
    dark: np.ndarray | None,
    flat: np.ndarray | None,
) -> np.ndarray:
    """
    Apply dark and flat-field correction: (frame - dark) / (flat - dark).
    If dark is None: treat as zeros (no dark subtraction).
    If flat is None: skip correction and return frame as float64.
    If both provided: full correction. Avoids division by zero by clamping denominator.
    """
    out = frame.astype(np.float64)

    if dark is None and flat is None:
        return out

    if dark is not None:
        if dark.shape != frame.shape:
            raise ValueError(f"dark shape {dark.shape} != frame shape {frame.shape}")
        out = out - dark

    if flat is not None:
        if flat.shape != frame.shape:
            raise ValueError(f"flat shape {flat.shape} != frame shape {frame.shape}")
        if dark is not None:
            denom = flat.astype(np.float64) - dark.astype(np.float64)
        else:
            denom = flat.astype(np.float64)
        # Avoid division by zero; use small epsilon
        denom = np.where(denom > 1.0, denom, 1.0)
        out = out / denom

    return out
