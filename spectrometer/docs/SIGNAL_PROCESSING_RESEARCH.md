# Signal Processing Opportunities for Spectrometer Performance Enhancement

**Purpose**: Research document evaluating signal processing techniques that can offset hardware/manufacturing tradeoffs in the camera-as-spectrometer system. Target platform: Raspberry Pi Zero 2 W, total processing budget <2 s per spectrum.

**Related**: [DARK_FLAT_CALIBRATION.md](DARK_FLAT_CALIBRATION.md) (acquiring dark/flat frames), [CODER_INSTRUCTIONS.md](CODER_INSTRUCTIONS.md) (implementation in `lib/signal_processing/`).

---

## 1. Executive Summary

Several signal processing techniques can significantly improve spectrometer performance without upgrading optics or mechanics. The most impactful opportunities are:


| Technique                    | Performance Gain               | Cost (Pi Zero 2 W) | Ease   | Priority |
| ---------------------------- | ------------------------------ | ------------------ | ------ | -------- |
| Deconvolution (slit/PSF)     | High (resolution recovery)     | Medium             | Medium | **High** |
| Dark + flat-field correction | High (sensitivity, uniformity) | Low                | High   | **High** |
| Frame averaging              | √n SNR improvement             | Low                | High   | **High** |
| Baseline correction          | Medium–High                    | Low                | High   | **High** |
| Savitzky–Golay smoothing     | Medium                         | Very low           | High   | Medium   |
| Wavelet denoising            | Medium                         | Low                | Medium | Medium   |
| Hot-pixel removal            | Low–Medium                     | Very low           | High   | Medium   |
| Derivative spectroscopy      | Medium (peak resolution)       | Low                | High   | Low      |
| Wiener deconvolution         | Medium                         | Low                | Medium | Low      |


**Key insight**: Using a wider slit increases light throughput (better sensitivity) but degrades resolution. Deconvolution can recover much of the lost resolution in software, enabling a hardware tradeoff that favors sensitivity.

**Weak signals** (near noise floor): Frame averaging, dark/flat correction, and careful baseline correction help most. Deconvolution, smoothing, and wavelet denoising can attenuate or remove weak signals if parameters are too aggressive — see per-technique notes below.

---

## 2. Hardware Context

### 2.1 Spectrometer Setup

- **Camera**: RAW-MIPI-SC132M (SC132GS CMOS, 1080×1280, 10-bit mono)
- **Typical line length**: ~800–1000 pixels (configurable)
- **Output**: 1D intensity array → wavelength calibration → spectrum
- **Current pipeline**: `extract_line_profile` → `compute_spectrum` (no post-processing)

### 2.2 Computational Budget

- **Platform**: Raspberry Pi Zero 2 W (quad-core ARM Cortex-A53 @ 1 GHz, 512 MB RAM)
- **Constraint**: Combined processing time <2 s per spectrum
- **Data size**: ~1000 points per spectrum (1D float64)
- **Libraries already in use**: NumPy, OpenCV, matplotlib, paho-mqtt
- **Additional dependencies acceptable**: SciPy, scikit-image, pybaselines, PyWavelets (if lightweight)

---

## 3. Signal Processing Techniques

### 3.1 Deconvolution (Slit / PSF Broadening)

**Concept**: The spectrometer slit and optics convolve the true spectrum with an instrument line shape (ILS). Deconvolution inverts this to recover sharper spectral features.

**Tradeoff enabled**: Use a **wider slit** → more light (higher sensitivity) → lower resolution. Deconvolution recovers resolution in software.

#### 3.1.1 Richardson–Lucy Deconvolution

- **Performance gain**: High. Can recover 30–50% of resolution lost to slit broadening when PSF is known or estimated.
- **Computational cost**: O(N × iter) with FFT-based convolution (O(N log N) per iteration). For N≈1000, 20–50 iterations: ~50–200 ms on Pi Zero 2 W (estimate).
- **Libraries**: `skimage.restoration.richardson_lucy` (works on 1D arrays). Requires scikit-image.
- **Ease**: Medium. Need to estimate or measure PSF (Gaussian or triangular slit function). Early stopping acts as regularization; too many iterations amplifies noise.
- **Notes**: Iteration count is a regularization knob. Start with 10–30 iterations; tune for SNR vs. sharpness.
- **Weak signals**: **Risky**. Deconvolution amplifies noise; weak peaks can be swamped or turn into artifacts. Use few iterations (5–15) and consider skipping deconvolution when SNR is very low. Wiener is safer than RL for weak signals.

#### 3.1.2 Wiener Deconvolution

- **Performance gain**: Medium. Less aggressive than Richardson–Lucy; better noise behavior at high frequencies.
- **Computational cost**: O(N log N) — single FFT pair. <10 ms for N≈1000.
- **Libraries**: Implement via `scipy.fft` (no built-in 1D Wiener; formula is straightforward). Or `skimage.restoration.unsupervised_wiener` (2D-oriented but adaptable).
- **Ease**: Medium. Requires PSF and noise/signal power estimates (or regularization constant).
- **Notes**: Good first choice for low-risk resolution recovery. Less prone to noise amplification than naive inverse filtering.
- **Weak signals**: **Safer than Richardson–Lucy**. Regularization constant suppresses high-frequency noise; weak signals are better preserved if SNR/regularization is tuned. Still test on low-SNR data before relying on it.

#### 3.1.3 Fourier Deconvolution (Inverse Filtering)

- **Performance gain**: High in theory, but noise amplification at high frequencies is severe.
- **Computational cost**: O(N log N). Very fast.
- **Ease**: Low (implementation trivial) but **not recommended** without regularization — Wiener or RL are preferred.
- **Weak signals**: **Harmful**. Uncontrolled noise amplification will obliterate weak signals. Do not use.

---

### 3.2 Dark and Flat-Field Correction

**Concept**: Subtract dark current (no light) and divide by flat field (uniform illumination) to correct pixel-to-pixel sensitivity and thermal noise.

- **Performance gain**: High. Removes fixed-pattern noise, vignetting, hot pixels; improves quantitative accuracy and effective sensitivity.
- **Computational cost**: O(N) — element-wise subtract and divide. <1 ms.
- **Libraries**: NumPy only. No extra dependencies.
- **Ease**: High. Requires acquiring dark and flat frames (one-time or periodic). Formula: `(raw - dark) / (flat - dark)`.
- **Notes**: Dark should match exposure time (or scale). Flat should be unsaturated. Essential for any serious spectrometry.
- **Weak signals**: **Beneficial**. Lowers effective noise floor by removing fixed-pattern noise and offsets; weak signals become more detectable. No attenuation of real signal.

---

### 3.3 Frame Averaging

**Concept**: Average N consecutive frames before extracting the spectrum. Random noise reduces by √N.

- **Performance gain**: √N SNR improvement. 4 frames → 2× SNR; 16 frames → 4× SNR.
- **Computational cost**: O(N × M) for N frames of M pixels. Negligible for N≤16, M≈1000. <5 ms.
- **Libraries**: NumPy `mean(axis=0)`.
- **Ease**: High. Integrate into capture loop; no new dependencies.
- **Notes**: Increases total acquisition time (N × exposure). Best combined with dark/flat correction.
- **Weak signals**: **Strongly beneficial**. Primary tool for weak-signal detection — √N SNR gain directly improves detectability. Weak signals reinforce across frames; random noise cancels. Prefer more frames over longer exposure when shot noise dominates.

---

### 3.4 Baseline Correction

**Concept**: Remove slow-varying background (detector drift, fluorescence, scattered light) so peaks stand out.

- **Performance gain**: Medium–High. Critical for quantitative peak analysis and low-concentration detection.
- **Computational cost**: Varies by algorithm. Polynomial: O(N). AsLS/airPLS: O(N) to O(N log N). Typically <50 ms for N≈1000.
- **Libraries**: **pybaselines** (50+ algorithms: AsLS, airPLS, ModPoly, SNIP, etc.). NumPy/SciPy only for simple polynomial.
- **Ease**: High. pybaselines has a unified API; ModPoly or AsLS are good defaults.
- **Notes**: Overfitting the baseline can remove real signal. Use conservative parameters.
- **Weak signals**: **Risky**. Algorithms (AsLS, airPLS, ModPoly) can mistake weak broad features for baseline and subtract them. Use low smoothness (e.g. high `lam` for AsLS), fit baseline only in known empty regions, or use SNIP (morphological) which tends to preserve weak peaks better. Validate on spectra with known weak features.

---

### 3.5 Savitzky–Golay Smoothing

**Concept**: Local polynomial fitting; smooths noise while preserving peak shape better than moving average.

- **Performance gain**: Medium. SNR improvement without heavy resolution loss if window and polynomial order are chosen carefully.
- **Computational cost**: O(N) via convolution. <5 ms for N≈1000.
- **Libraries**: `scipy.signal.savgol_filter`. Already in SciPy (add to requirements).
- **Ease**: High. Two parameters: `window_length` (odd, e.g. 11–21), `polyorder` (e.g. 3–5).
- **Notes**: Can also compute derivatives (`deriv=1` or `2`) for derivative spectroscopy.
- **Weak signals**: **Risky**. Large window or high polyorder can smooth away weak narrow peaks. Use small window (e.g. 7–11) and low polyorder (2–3) to preserve weak features; accept less noise reduction. Test on synthetic weak peaks before applying to real data.

---

### 3.6 Wavelet Denoising

**Concept**: Decompose spectrum into wavelet coefficients; threshold small (noise) coefficients; reconstruct.

- **Performance gain**: Medium. Often preserves sharp peaks better than Savitzky–Golay.
- **Computational cost**: O(N). <20 ms for N≈1000.
- **Libraries**: **PyWavelets** (`pywt`). Lightweight, pure Python/NumPy.
- **Ease**: Medium. Requires choosing wavelet (e.g. `db4`, `sym4`) and threshold (e.g. universal, BayesShrink).
- **Notes**: Good alternative to SG when peaks are narrow. Can over-smooth if threshold too aggressive.
- **Weak signals**: **Risky**. Universal or BayesShrink thresholds assume noise dominates; weak signal coefficients can fall below threshold and be zeroed. Use soft thresholding and lower multiplier (e.g. 0.5× universal) or level-dependent thresholds. Consider skipping wavelet denoising when hunting for weak signals.

---

### 3.7 Hot-Pixel / Outlier Removal

**Concept**: Detect and replace anomalous pixels (hot pixels, cosmic rays, readout glitches).

- **Performance gain**: Low–Medium. Removes spikes that can distort peaks or calibration.
- **Computational cost**: O(N) for median filter; O(N) for MAD-based detection. <5 ms.
- **Libraries**: `scipy.ndimage.median_filter` or `scipy.signal.medfilt`. Or simple MAD: `|x - median| > k * MAD` → replace with median.
- **Ease**: High. Small kernel (3–5 pixels) usually sufficient.
- **Notes**: Median filter can broaden narrow peaks slightly. Use sparingly or only on flagged pixels.
- **Weak signals**: **Generally safe**. Only replaces clear outliers (e.g. >5σ). A weak real peak spanning several pixels is unlikely to be flagged. Risk: a single-pixel weak spike could be removed if mistaken for hot pixel — use high threshold (e.g. 5–6× MAD) and prefer MAD over median filter to minimize collateral smoothing.

---

### 3.8 Derivative Spectroscopy

**Concept**: First or second derivative enhances resolution of overlapping peaks (zeros of derivative between peaks).

- **Performance gain**: Medium for peak resolution. Second derivative sharpens peaks; helps separate overlapping bands.
- **Computational cost**: Same as Savitzky–Golay with `deriv=1` or `2`. <5 ms.
- **Libraries**: `scipy.signal.savgol_filter(..., deriv=1)` or `deriv=2`.
- **Ease**: High. Single parameter change.
- **Notes**: Amplifies high-frequency noise. Apply only after smoothing, or use SG with derivative in one step.
- **Weak signals**: **Harmful**. Derivatives amplify noise; weak signals are often already near noise level — first/second derivative can completely obscure them. Avoid derivative spectroscopy when weak-signal detection is the goal. Use only on well-smoothed, high-SNR spectra.

---

### 3.9 Calibration Refinement

**Concept**: Iteratively remove calibration outliers (lines with large residuals) to improve wavelength accuracy.

- **Performance gain**: Low–Medium. Improves wavelength accuracy, especially at edges.
- **Computational cost**: O(k) where k = number of calibration points. Negligible.
- **Libraries**: NumPy. Already have `fit_calibration`; add residual-based rejection loop.
- **Ease**: High. Fits existing calibration workflow.
- **Notes**: Useful during calibration phase; less relevant for runtime processing.
- **Weak signals**: Neutral. No direct impact.

---

### 3.10 Spectral Interpolation / Resampling

**Concept**: Resample spectrum to uniform wavelength grid (e.g. 1 nm steps) for consistent comparison and integration.

- **Performance gain**: Low. Enables downstream analysis; no direct SNR or resolution gain.
- **Computational cost**: O(N). `scipy.interpolate.interp1d` or `numpy.interp`. <5 ms.
- **Ease**: High.
- **Notes**: Useful if pixel-to-wavelength mapping is nonlinear and downstream expects regular grid.

---

## 4. Computational Budget Estimate (Pi Zero 2 W)

Approximate times for N≈1000, single spectrum (order-of-magnitude):


| Step                                   | Time (ms)    |
| -------------------------------------- | ------------ |
| Dark + flat correction                 | <1           |
| Frame averaging (8 frames)             | ~2           |
| Hot-pixel removal                      | ~2           |
| Baseline correction (pybaselines AsLS) | ~20–50       |
| Savitzky–Golay smoothing               | ~2           |
| Richardson–Lucy (30 iter)              | ~50–150      |
| Wiener deconvolution                   | ~5           |
| Wavelet denoising                      | ~10–20       |
| **Total (full pipeline)**              | **~100–250** |


**Conclusion**: A full pipeline of corrections + deconvolution fits comfortably within 2 s. Most time will be in capture (exposure × N frames) rather than processing.

---

## 5. Implementation Priority

### Phase 1 — Quick Wins (minimal dependencies)

1. **Dark + flat-field correction** — Essential, trivial cost.
2. **Frame averaging** — Integrate into capture; configurable N.
3. **Hot-pixel removal** — Simple median or MAD; prevents artifacts.

### Phase 2 — Core Enhancements (add SciPy)

1. **Baseline correction** — pybaselines (AsLS or ModPoly) or simple polynomial.
2. **Savitzky–Golay smoothing** — Optional pre-step before deconvolution or as standalone.
3. **Wiener deconvolution** — Lower risk than Richardson–Lucy; good first deconvolution.

### Phase 3 — Advanced (add scikit-image, optional PyWavelets)

1. **Richardson–Lucy deconvolution** — When PSF is known/estimated; tune iterations.
2. **Wavelet denoising** — Alternative to SG if peak preservation is critical.
3. **Derivative spectroscopy** — If peak resolution is a key use case.

### Weak-Signal Priority (when preserving near-noise signals)

| Technique | Weak-signal impact | Recommendation |
|-----------|--------------------|----------------|
| Frame averaging | **Beneficial** | Use liberally; primary tool for weak signals |
| Dark + flat correction | **Beneficial** | Always apply |
| Baseline correction | **Risky** | Use conservative params; prefer SNIP or fit in empty regions |
| Hot-pixel removal | **Generally safe** | Use high threshold (5–6× MAD) |
| Wiener deconvolution | **Safer** | Prefer over Richardson–Lucy; tune regularization |
| Richardson–Lucy | **Risky** | Few iterations; consider skipping at low SNR |
| Savitzky–Golay | **Risky** | Small window (7–11), low polyorder |
| Wavelet denoising | **Risky** | Soft threshold, lower multiplier; or skip |
| Derivative spectroscopy | **Harmful** | Avoid when hunting weak signals |

---

## 6. Library Summary


| Library          | Purpose                                  | Size / Impact                                 |
| ---------------- | ---------------------------------------- | --------------------------------------------- |
| **SciPy**        | savgol_filter, fft, ndimage, interpolate | Standard; add to requirements                 |
| **pybaselines**  | Baseline correction (50+ algorithms)     | Lightweight; NumPy/SciPy only                 |
| **scikit-image** | Richardson–Lucy deconvolution            | Moderate; consider if deconvolution is needed |
| **PyWavelets**   | Wavelet denoising                        | Lightweight; optional                         |


**Recommendation**: Add `scipy` and `pybaselines` first. Add `scikit-image` if Richardson–Lucy is required. PyWavelets is optional.

---

## 7. PSF / Slit Function Estimation

For deconvolution to work, the instrument line shape (ILS) must be known or estimated.

**Options**:

1. **Theoretical**: Model slit as rectangular (top-hat) or triangular. Width from mechanical slit size + dispersion.
2. **Empirical**: Use a narrow emission line (e.g. laser, LED, calibration lamp) — its image is the ILS.
3. **Blind estimation**: Homomorphic filtering or cepstral analysis can estimate slit width from spectra (literature: Appl. Opt. 23, 1601). More complex; consider only if slit is unknown.

**Practical approach**: Start with Gaussian PSF, σ ≈ (slit_width_pixels) / 2.35. Tune empirically using a known narrow line.

---

## 8. References and Further Reading

- Homomorphic filtering for slit width estimation: Appl. Opt. 23(10), 1601 (1984)
- Richardson–Lucy: skimage.restoration.richardson_lucy
- pybaselines: [https://pybaselines.readthedocs.io](https://pybaselines.readthedocs.io)
- Frame/bin SNR: √n improvement (standard)
- Flat-field correction: (raw - dark) / (flat - dark)

---

## 9. Document History

- **Created**: 2025-03-07 — Research phase; no code written.
- **Updated**: 2025-03-07 — Added weak-signal impact notes for each technique; weak-signal priority table.
- **Status**: Ready for coder implementation planning.

