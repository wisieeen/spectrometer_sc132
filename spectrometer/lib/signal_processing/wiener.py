"""
Wiener deconvolution for 1D spectra.
Recovers resolution lost to slit/PSF broadening. Uses regularization to limit noise amplification.
Independent module; no dependencies on other processing techniques.

PSF is ifftshifted before FFT so the kernel center is at index 0; otherwise FFT-based
deconvolution introduces a phase shift that manifests as a wavelength shift in the spectrum.
"""
import numpy as np


def _gaussian_psf(n: int, sigma_px: float) -> np.ndarray:
    """Create centered Gaussian PSF of length n, normalized to sum=1."""
    x = np.arange(n, dtype=np.float64) - (n - 1) / 2.0
    psf = np.exp(-(x**2) / (2 * sigma_px**2))
    psf /= psf.sum()
    return psf


def wiener_deconvolve(
    signal: np.ndarray,
    psf_sigma_px: float = 3.0,
    regularization: float = 0.01,
) -> np.ndarray:
    """
    Wiener deconvolution of 1D signal.
    Formula: result = IFFT(S * conj(H) / (|H|² + reg²))

    Args:
        signal: 1D intensity array (spectrum).
        psf_sigma_px: Gaussian PSF sigma in pixels (≈ slit width / 2.35).
        regularization: Noise regularization (0.001–0.1). Higher = less sharpening, less noise.

    Returns:
        Deconvolved 1D array, same length as signal.
    """
    signal = np.asarray(signal, dtype=np.float64)
    if signal.ndim != 1:
        raise ValueError("signal must be 1D array")
    n = len(signal)
    if n < 3:
        return signal.copy()

    psf = _gaussian_psf(n, max(0.5, psf_sigma_px))
    psf = np.fft.ifftshift(psf)  # Center kernel at index 0 for correct FFT convolution (avoids phase shift)
    reg = max(1e-6, float(regularization))

    H = np.fft.rfft(psf, n=n)
    S = np.fft.rfft(signal.astype(np.float64), n=n)

    denom = np.abs(H) ** 2 + reg**2
    result = np.fft.irfft(S * np.conj(H) / denom, n=n)

    return np.clip(result, 0, None).astype(np.float64)
