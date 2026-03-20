# Richardson–Lucy Deconvolution

Optional deconvolution step for spectrometer signal processing. Recovers resolution lost to slit/PSF broadening.

## Overview

- **Algorithm**: Richardson–Lucy iterative deconvolution (custom implementation)
- **Purpose**: Sharpen spectral peaks; recover resolution when using a wider slit for higher sensitivity

## Parameters

| Parameter | Config key | Range | Default | Description |
|-----------|------------|-------|---------|-------------|
| Enabled | `richardson_lucy_enabled` | bool | false | Toggle Richardson–Lucy |
| PSF sigma | `richardson_lucy_psf_sigma` | 0.5–20 px | 3.0 | Gaussian PSF sigma (fallback when no custom PSF) |
| Custom PSF path | `richardson_lucy_psf_path` | path | null | Path to .npy file with 1D PSF (measured/custom). Overrides sigma. |
| Iterations | `richardson_lucy_iterations` | 1–100 | 15 | Number of RL iterations; fewer = less sharpening, less noise |

## Control

- **MQTT**: `cmd/processing_richardson_lucy_enabled`, `cmd/processing_richardson_lucy_psf_sigma`, `cmd/processing_richardson_lucy_psf_path`, `cmd/processing_richardson_lucy_iterations`
- **REST**: `POST /api/spectrometer/processing_richardson_lucy_*` with `{ value: ... }`
- **Web UI**: Spectrometer tab → Richardson–Lucy checkbox, PSF sigma, iterations, custom PSF path

---

## Non-Gaussian PSF and Slit Shape

The current implementation uses a **Gaussian PSF**. Real slit shapes produce different instrument line shapes (ILS):

| Slit shape | 1D PSF (dispersion axis) | Gaussian approximation |
|------------|--------------------------|-------------------------|
| **Rectangular** | Top-hat (flat, sharp edges) | Fair. Gaussian is smoother; use σ ≈ FWHM/2.35. |
| **Round / circular** | Rounded, semi-circular (projection of circle onto line) | Good. Often well approximated; diffraction and aberrations soften edges. |
| **Triangular** | Linear falloff | Fair. Gaussian is fatter in center; tune σ empirically. |
| **Elliptical** | Depends on orientation | Good if major axis along dispersion; treat as Gaussian. |

**Why Gaussian often works**:
- Diffraction and optical aberrations soften sharp slit edges in practice.
- Gaussian is smooth and numerically stable for deconvolution.
- σ is a single knob; easy to tune empirically.

**When Gaussian may underperform**:
- Very sharp rectangular slit with minimal diffraction → top-hat PSF; Gaussian can cause ringing.
- Strongly non-Gaussian measured ILS → consider empirical PSF (see below).

**Custom / measured PSF**: Set `richardson_lucy_psf_path` to a `.npy` file containing a 1D NumPy array. The array is normalized to sum=1, centered (peak at middle), and can be shorter than the spectrum. Leave empty to use Gaussian with `richardson_lucy_psf_sigma`.

---

## Parameter Tuning Guide

### PSF sigma (`richardson_lucy_psf_sigma`)

**Initial estimate**:
- σ ≈ (slit_width_pixels) / 2.35, where slit width is the FWHM of the blur in pixels.
- If you know mechanical slit width in mm: convert to pixels using dispersion (nm/pixel) and optical magnification.

**Empirical tuning**:
1. Use a **narrow emission line** (laser, LED, calibration lamp).
2. Measure its FWHM in pixels on the sensor (before deconvolution).
3. Start with σ = FWHM / 2.35.
4. Adjust: **larger σ** → more deconvolution (sharper, but more noise); **smaller σ** → less effect. If peaks become too sharp and noisy, reduce σ or iterations.

**Round slit**: Same formula. The 1D projection of a round slit is often Gaussian-like; start with σ from FWHM of a narrow line and fine-tune.

### Iterations (`richardson_lucy_iterations`)

**Tradeoff**: More iterations → sharper peaks, but more noise amplification.

| SNR | Suggested range | Notes |
|-----|-----------------|------|
| High (strong peaks) | 20–50 | Maximize resolution recovery |
| Medium | 10–20 | Good default |
| Low (weak signals) | 5–15 | Use fewer iterations |
| Very low | 0 (off) | Skip deconvolution |

**Early stopping**: Iteration count acts as regularization. Stop before noise dominates; typical sweet spot is 10–30 for most spectra.

**Signs of over-iteration**:
- Peaks develop overshoot/ringing.
- Baseline becomes noisy or oscillatory.
- Weak peaks turn into artifacts.

**Signs of under-iteration**:
- Peaks still noticeably broad.
- Resolution recovery is modest.

---

## Maximizing Performance

### Processing order

1. **Frame averaging** before deconvolution (higher SNR → fewer artifacts).
2. **Dark/flat correction** before deconvolution (removes fixed-pattern noise).

The pipeline applies these in the correct order automatically.

### SNR and frame averaging

- Deconvolution amplifies noise. Use **frame_average_n ≥ 4** (or higher) when SNR is marginal.
- For weak signals, prefer fewer iterations or disable deconvolution.

### Measuring PSF empirically (custom PSF)

Use the `measure_psf.py` script:

1. Illuminate with a **narrow emission line** (laser, LED, calibration lamp).
2. Stop the RTSP stream.
3. Run:
   ```bash
   python scripts/measure_psf.py -o /path/to/psf.npy
   ```
4. Set `richardson_lucy_psf_path` in config or Web UI to `/path/to/psf.npy`.

**Options**: `-n N` (frames to average), `-c N` (channel index), `--no-dark-flat`, `-f frame.npy` (use existing frame), `--config PATH` (spectrometer config).

**Verify PSF**: Run `python scripts/display_psf.py /path/to/psf.npy` to check peak centering and shape. `measure_psf.py` produces centered PSFs; non-centered PSF causes shift artifacts.

### Common pitfalls

| Issue | Cause | Fix |
|-------|-------|-----|
| Ringing / overshoot | Oversharpening; σ too small or iterations too high | Reduce iterations; increase σ slightly |
| No visible improvement | σ too large; PSF too broad | Decrease σ; verify with narrow line |
| Noise explosion | Too many iterations; low SNR | Fewer iterations; use frame averaging |
| **Spectrum shift / values inflated** | **PSF not centered; baseline wrong; too many iterations** | Use `measure_psf.py` (centers PSF); run `display_psf.py` to verify; reduce iterations; see [PSF_SHIFT_INVESTIGATION.md](PSF_SHIFT_INVESTIGATION.md) |

---

## Weak-Signal Notes

Richardson–Lucy amplifies noise. For weak signals (near noise floor), use few iterations (5–15). See [SIGNAL_PROCESSING_RESEARCH.md](SIGNAL_PROCESSING_RESEARCH.md).

---

## Implementation Notes

Richardson–Lucy uses **spatial convolution** (`numpy.convolve`, mode='same') with zero-padding at boundaries — no FFT, so no circular wrap-around or phase shift. PSF in natural (centered) spatial order. NumPy only.

## Dependency

NumPy only. No scikit-image required.
