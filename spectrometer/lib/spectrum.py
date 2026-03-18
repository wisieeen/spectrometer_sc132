"""
Line extraction, calibration, spectrum computation.
- Extract 1D intensity profile along line with thickness (sum perpendicular pixels).
- Map pixel index to wavelength via linear or polynomial fit.
"""
import numpy as np
from typing import List, Tuple, Optional


def extract_line_profile(
    frame: np.ndarray,
    start: Tuple[int, int],
    end: Tuple[int, int],
    thickness: int,
) -> np.ndarray:
    """
    Extract intensity profile along line from start to end.
    For each point along the line, sum pixels in a strip of `thickness` perpendicular to the line.
    Returns 1D array of intensities (length = number of pixels along line).
    """
    if not isinstance(frame, np.ndarray) or frame.size == 0:
        return np.array([])
    if frame.ndim not in (2, 3):
        raise ValueError("frame must be 2D or 3D")
    thickness = max(1, min(int(thickness), 100))

    x1, y1 = start
    x2, y2 = end
    length = int(np.hypot(x2 - x1, y2 - y1))
    if length == 0:
        return np.array([])

    # Ensure 2D (Y10/OpenCV may return 3D)
    if len(frame.shape) == 3:
        frame = frame[:, :, 0] if frame.shape[2] == 1 else np.mean(frame, axis=2)

    # Unit vector along line
    dx = (x2 - x1) / length
    dy = (y2 - y1) / length
    # Perpendicular unit vector
    px = -dy
    py = dx

    h, w = frame.shape
    half_t = thickness // 2
    intensities = []

    for i in range(length):
        cx = x1 + i * dx
        cy = y1 + i * dy
        strip_values = []
        for j in range(-half_t, half_t + 1):
            sx = int(cx + j * px)
            sy = int(cy + j * py)
            if 0 <= sx < w and 0 <= sy < h:
                strip_values.append(frame[sy, sx])
        intensities.append(float(np.mean(strip_values)) if strip_values else 0.0)

    return np.array(intensities, dtype=np.float64)


def fit_calibration(
    pairs: List[Tuple[float, float]],
    fit_type: str = "linear",
    degree: int = 2,
) -> np.ndarray:
    """
    Fit pixel -> wavelength. pairs = [(pixel_index, wavelength_nm), ...].
    Returns coefficients for np.polyval (order: high to low).
    """
    if not pairs or len(pairs) < 2:
        raise ValueError("pairs must have at least 2 points")
    try:
        pixels = np.array([float(p[0]) for p in pairs])
        wavelengths = np.array([float(p[1]) for p in pairs])
    except (IndexError, TypeError, ValueError):
        raise ValueError("pairs must be [(pixel, wavelength), ...] with numeric values")
    if fit_type == "linear":
        return np.polyfit(pixels, wavelengths, 1)
    return np.polyfit(pixels, wavelengths, min(degree, len(pairs) - 1))


def pixel_to_wavelength(
    pixel_indices: np.ndarray,
    coeffs: np.ndarray,
) -> np.ndarray:
    """Map pixel indices to wavelengths using polynomial coefficients."""
    return np.polyval(coeffs, pixel_indices)


def compute_spectrum(
    intensities: np.ndarray,
    coeffs: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Map raw intensity profile to (wavelengths_nm, intensities).
    """
    intensities = np.asarray(intensities, dtype=np.float64)
    if intensities.size == 0:
        return np.array([]), np.array([])
    coeffs = np.asarray(coeffs, dtype=np.float64)
    if coeffs.ndim != 1:
        raise ValueError("coeffs must be 1D array")
    pixels = np.arange(len(intensities))
    wavelengths = pixel_to_wavelength(pixels, coeffs)
    return wavelengths, intensities
