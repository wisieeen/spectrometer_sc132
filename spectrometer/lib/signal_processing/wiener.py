"""
Wiener deconvolution for 1D spectra.
Recovers resolution lost to slit/PSF broadening. Uses regularization to limit noise amplification.
Independent module; no dependencies on other processing techniques.

Supports custom/measured PSF via psf_path (.npy file), same format as Richardson–Lucy.
PSF is zero-padded to signal length and ifftshifted before FFT.

When dark_spectrum is provided (1D line extracted from dark frame, same geometry as signal),
uses full Wiener formula: denom = |H|² + S_nn/S_xx with noise power S_nn from dark.
Otherwise falls back to fixed regularization (Tikhonov-style).
"""
import os
import numpy as np


def _gaussian_psf(n: int, sigma_px: float) -> np.ndarray:
    """Create centered Gaussian PSF of length n, normalized to sum=1."""
    x = np.arange(n, dtype=np.float64) - (n - 1) / 2.0
    psf = np.exp(-(x**2) / (2 * sigma_px**2))
    psf /= psf.sum()
    return psf


def _load_psf(path: str | None, n: int) -> np.ndarray | None:
    """Load 1D PSF from .npy, pad to length n, return ifftshifted. None if invalid."""
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
        # Zero-pad to signal length, centered
        if len(arr) < n:
            pad_total = n - len(arr)
            pad_left = pad_total // 2
            pad_right = pad_total - pad_left
            arr = np.pad(arr, (pad_left, pad_right), mode="constant", constant_values=0.0)
        elif len(arr) > n:
            start = (len(arr) - n) // 2
            arr = arr[start : start + n].copy()
        return np.fft.ifftshift(arr)
    except Exception:
        return None


def wiener_deconvolve(
    signal: np.ndarray,
    psf_sigma_px: float = 3.0,
    regularization: float = 0.01,
    psf_path: str | None = None,
    dark_spectrum: np.ndarray | None = None,
) -> np.ndarray:
    """
    Wiener deconvolution of 1D signal.
    When dark_spectrum is provided: denom = |H|² + S_nn/S_xx (full Wiener, noise from dark).
    Otherwise: denom = |H|² + reg² (fixed regularization).

    Args:
        signal: 1D intensity array (spectrum).
        psf_sigma_px: Gaussian PSF sigma in pixels (fallback when no custom PSF).
        regularization: Fallback regularization when dark_spectrum is None (0.001–0.1).
        psf_path: Path to .npy file with 1D PSF (measured/custom). Overrides psf_sigma_px.
        dark_spectrum: 1D line from dark frame (same geometry as signal). Used for S_nn.

    Returns:
        Deconvolved 1D array, same length as signal.
    """
    signal = np.asarray(signal, dtype=np.float64)
    if signal.ndim != 1:
        raise ValueError("signal must be 1D array")
    n = len(signal)
    if n < 3:
        return signal.copy()

    loaded = _load_psf(psf_path, n) if psf_path else None
    if loaded is not None:
        psf = loaded
    else:
        psf = _gaussian_psf(n, max(0.5, psf_sigma_px))
        psf = np.fft.ifftshift(psf)

    reg = max(1e-6, float(regularization))

    H = np.fft.rfft(psf, n=n)
    S = np.fft.rfft(signal.astype(np.float64), n=n)

    # Noise-to-signal ratio: from dark when available, else fixed reg²
    if dark_spectrum is not None:
        dark_arr = np.asarray(dark_spectrum, dtype=np.float64).ravel()
        if len(dark_arr) >= 3:
            # Pad or truncate dark to match signal length
            if len(dark_arr) != n:
                if len(dark_arr) < n:
                    pad_total = n - len(dark_arr)
                    pad_left = pad_total // 2
                    pad_right = pad_total - pad_left
                    dark_arr = np.pad(
                        dark_arr, (pad_left, pad_right), mode="edge"
                    )
                else:
                    start = (len(dark_arr) - n) // 2
                    dark_arr = dark_arr[start : start + n].copy()
            D = np.fft.rfft(dark_arr, n=n)
            S_nn = np.abs(D) ** 2
            S_gg = np.abs(S) ** 2
            S_xx = np.maximum(S_gg - S_nn, 1e-12)
            ratio = np.clip(S_nn / S_xx, reg**2, 1e2)
            denom = np.abs(H) ** 2 + ratio
        else:
            denom = np.abs(H) ** 2 + reg**2
    else:
        denom = np.abs(H) ** 2 + reg**2

    result = np.fft.irfft(S * np.conj(H) / denom, n=n)

    return np.clip(result, 0, None).astype(np.float64)
