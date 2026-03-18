"""
Richardson–Lucy deconvolution for 1D spectra.
Recovers resolution lost to slit/PSF broadening. Iteration count acts as regularization.
Independent module; no dependencies on other processing techniques.

Uses numpy.convolve(mode='same') — spatial convolution with zero-padding at boundaries.
No FFT, so no circular wrap-around. PSF kept in natural (centered) order for spatial conv.

Supports custom/measured PSF via psf_path (.npy file) or psf array.
PSF must be centered (peak at middle); measure_psf.py produces this format.
"""
import os
import numpy as np


def _gaussian_psf(n: int, sigma_px: float) -> np.ndarray:
    """Create centered Gaussian PSF of length n, normalized to sum=1."""
    x = np.arange(n, dtype=np.float64) - (n - 1) / 2.0
    psf = np.exp(-(x**2) / (2 * sigma_px**2))
    psf /= psf.sum()
    return psf


def _load_psf(path: str | None) -> np.ndarray | None:
    """Load 1D PSF from .npy file. Returns None if path is empty or file invalid."""
    if not path or not isinstance(path, str):
        return None
    path = path.strip()
    if not path or not os.path.isfile(path):
        return None
    try:
        arr = np.load(path)
        arr = np.asarray(arr, dtype=np.float64).ravel()
        if len(arr) < 3:
            return None
        arr = np.clip(arr, 0, None)
        s = arr.sum()
        if s <= 0:
            return None
        arr /= s
        return arr
    except Exception:
        return None


def richardson_lucy_deconvolve(
    signal: np.ndarray,
    psf_sigma_px: float = 3.0,
    num_iterations: int = 15,
    psf_path: str | None = None,
    psf: np.ndarray | None = None,
) -> np.ndarray:
    """
    Richardson–Lucy deconvolution of 1D signal.
    Uses spatial convolution (numpy.convolve, mode='same') with zero-padding — no FFT,
    so no shift or wrap-around artifacts.

    Args:
        signal: 1D intensity array (spectrum).
        psf_sigma_px: Gaussian PSF sigma in pixels (fallback when no custom PSF).
        num_iterations: Number of RL iterations (5–30 typical). Higher = sharper, more noise.
        psf_path: Path to .npy file with 1D PSF (measured or custom). Overrides psf_sigma_px.
        psf: 1D PSF array directly. Overrides psf_path and psf_sigma_px if provided.

    Returns:
        Deconvolved 1D array, same length as signal.
    """
    signal = np.asarray(signal, dtype=np.float64)
    if signal.ndim != 1:
        raise ValueError("signal must be 1D array")
    n = len(signal)
    if n < 3:
        return signal.copy()

    # Resolve PSF: custom array > path > Gaussian
    if psf is not None:
        psf = np.asarray(psf, dtype=np.float64).ravel()
        if len(psf) < 3:
            psf = _gaussian_psf(n, max(0.5, psf_sigma_px))
        else:
            psf = np.clip(psf, 0, None)
            s = psf.sum()
            if s <= 0:
                psf = _gaussian_psf(n, max(0.5, psf_sigma_px))
            else:
                psf = psf / s
    elif psf_path:
        loaded = _load_psf(psf_path)
        psf = loaded if loaded is not None else _gaussian_psf(n, max(0.5, psf_sigma_px))
    else:
        psf = _gaussian_psf(n, max(0.5, psf_sigma_px))

    psf_mirror = np.flip(psf)
    iters = max(1, min(100, int(num_iterations)))

    eps = 1e-12
    im_deconv = np.full(n, 0.5, dtype=np.float64)

    for _ in range(iters):
        conv1 = np.convolve(im_deconv, psf, mode="same") + eps
        relative_blur = np.where(conv1 < eps, 0.0, signal / conv1)
        im_deconv *= np.convolve(relative_blur, psf_mirror, mode="same")

    return np.clip(im_deconv, 0, None).astype(np.float64)
