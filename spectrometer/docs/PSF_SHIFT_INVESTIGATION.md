# Richardson–Lucy: Spectrum Shift Toward Larger Values — Investigation

## Problem

Processed spectrum is heavily shifted toward larger values after Richardson–Lucy deconvolution with custom PSF.

## Root Causes

### 1. **PSF not centered** (primary)

`numpy.convolve(..., mode='same')` assumes the kernel is centered: the peak must be at index `len(psf)//2`. A measured line profile from `measure_psf.py` can have its peak anywhere (depends on ROI, line position, optical asymmetry). A non-centered PSF causes:

- **Wavelength shift**: spectral features move along the dispersion axis
- **Intensity artifacts**: incorrect deconvolution response

**Fix**: `measure_psf.py` centers the PSF (peak at center) and crops symmetrically before saving. Richardson–Lucy and Wiener expect this format.

### 2. **Baseline subtraction in PSF extraction**

`measure_psf.py` uses `baseline_frac` (default 10%) at each end to estimate baseline. If the profile is asymmetric or the line is near an edge, baseline can be wrong → asymmetric PSF → shift/artifacts.

**Fix**: Use `--baseline-frac` to tune; ensure the line is centered in the ROI; run `display_psf.py` to inspect.

### 3. **Too many iterations**

RL amplifies signal; excess iterations can inflate values.

**Fix**: Reduce `richardson_lucy_iterations` (try 5–10).

### 4. **PSF shape mismatch**

If the measured PSF is too narrow or too broad vs. actual blur, RL converges poorly.

**Fix**: Verify FWHM with `display_psf.py`; compare with narrow-line FWHM before deconvolution.

## Diagnostics

```bash
python scripts/display_psf.py /path/to/psf.npy
```

Check:
- **Peak offset from center**: should be 0
- **Sum**: should be ~1.0
- **Shape**: symmetric, no long asymmetric tails

## Coder Notes

- `measure_psf.py`: Centers PSF and crops symmetrically (50 px from peak) before save. Output is ready for Richardson–Lucy and Wiener.
- `richardson_lucy.py` and `wiener.py`: Use `richardson_lucy_psf_path` for custom PSF. Both techniques share the same path.
