"""
Frame averaging: average N frames to improve SNR by √N.
Independent module; no dependencies on other processing techniques.
"""
import numpy as np


def average_frames(frames: list) -> np.ndarray:
    """
    Average a list of frames. Returns float64 array for downstream compatibility.
    """
    if not frames:
        raise ValueError("frames must not be empty")
    stacked = np.stack(frames, axis=0)
    return np.mean(stacked, axis=0).astype(np.float64)
