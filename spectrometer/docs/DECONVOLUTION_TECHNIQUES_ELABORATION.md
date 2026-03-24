# Deconvolution Techniques: Detailed Elaboration

**Purpose**: Deep dive into deconvolution methods beyond Richardson–Lucy and Wiener. For research context and implementation priority, see [SIGNAL_PROCESSING_RESEARCH.md](SIGNAL_PROCESSING_RESEARCH.md) §3.1.

**Problem**: Observed spectrum \( g = h * x + n \), where \( h \) is the PSF (instrument line shape), \( x \) is the true spectrum, \( n \) is noise. We want to recover \( x \) from \( g \) given \( h \).

---

## 1. Tikhonov Regularization (Regularized Least Squares)

### Idea

Instead of naively inverting the convolution (which amplifies noise), Tikhonov minimizes a trade-off: fit the data **and** keep the solution smooth.

### Math

Minimize:
\[
\|h * x - g\|^2 + \lambda \|x\|^2
\]

In the frequency domain, the solution is:
\[
\hat{X}(f) = \frac{G(f) \cdot \overline{H(f)}}{|H(f)|^2 + \lambda^2}
\]

So the deconvolved spectrum is:
\[
x = \mathcal{F}^{-1}\left[ \frac{G \cdot \overline{H}}{|H|^2 + \lambda^2} \right]
\]

### Parameters

- **λ (lambda)**: Regularization parameter. Larger λ → smoother result, less noise amplification, less sharpening. Smaller λ → sharper but noisier. Typical range: 0.001–0.1 (similar to Wiener’s regularization).

### Relation to Wiener

Wiener uses \( |H|^2 + \frac{S_{nn}}{S_{xx}} \) in the denominator, where \( S_{nn} \) is noise power and \( S_{xx} \) is signal power. Tikhonov replaces that ratio with a single constant λ². So Tikhonov is Wiener with a fixed “noise-to-signal” assumption.

**Noise from dark frame**: The spectrometer Wiener implementation accepts `dark_spectrum` (1D line extracted from dark frame, same geometry as signal). When provided, it computes S_nn from dark power spectrum and S_xx = max(|G|^2 - S_nn, eps) per frequency, giving data-driven regularization. Otherwise falls back to fixed `regularization` (Tikhonov-style).

### Pros / Cons

| Pros | Cons |
|------|------|
| Non-iterative, single FFT pair | Less adaptive than Wiener (no SNR estimate) |
| Very fast O(N log N) | Single knob may not suit all SNR regimes |
| Simple to implement | |
| Stable, predictable | |

### Implementation sketch

```python
# Same structure as Wiener; only denominator differs
H = np.fft.rfft(psf, n=n)
G = np.fft.rfft(signal, n=n)
denom = np.abs(H)**2 + lambda_sq
x = np.fft.irfft(G * np.conj(H) / denom, n=n)
```

---

## 2. Landweber Iteration

### Idea

Landweber is gradient descent on the least-squares objective \( \|h*x - g\|^2 \). Each step moves the estimate in the direction that reduces the residual.

### Math

Update rule:
\[
x_{k+1} = x_k + \omega \cdot h^{\mathrm{flip}} * (g - h * x_k)
\]

In words: convolve current estimate with PSF, subtract from observed data, convolve the residual with the flipped PSF (adjoint), scale by step size ω, add to current estimate.

Equivalently (gradient form):
\[
x_{k+1} = x_k - \omega \cdot \nabla \|h*x_k - g\|^2
\]

### Parameters

- **ω (omega)**: Step size. Must satisfy \( 0 < \omega < 2/\sigma_1^2 \), where σ₁ is the largest singular value of the convolution operator. For a normalized PSF, σ₁ ≈ 1, so ω ∈ (0, 2) is typical. Practical range: 0.5–1.5.
- **Iterations**: Acts as regularization. Early iterations improve the estimate; later ones amplify noise (semi-convergence). Stop when \( \|h*x_k - g\| \) roughly matches the noise level, or use a fixed 20–50 iterations.

### Constrained variant

Project onto non-negative values each iteration:
\[
x_{k+1} = \max\left(0,\; x_k + \omega \cdot h^{\mathrm{flip}} * (g - h * x_k) \right)
\]

This enforces positivity, which is natural for spectra.

### Pros / Cons

| Pros | Cons |
|------|------|
| Iterative, can add constraints (positivity) | Semi-convergence: must stop early |
| Step size and iterations give two knobs | O(N × iter) cost |
| Well-understood theory | Sensitive to noise if run too long |
| Related to Tikhonov (implicit regularization) | |

### Implementation sketch

```python
psf_flip = np.flip(psf)
x = signal.copy().astype(np.float64)
for _ in range(num_iter):
    residual = signal - np.convolve(x, psf, mode='same')
    x = x + omega * np.convolve(residual, psf_flip, mode='same')
    x = np.clip(x, 0, None)  # optional positivity
```

---

## 3. Van Cittert Deconvolution

### Idea

Van Cittert (1931) is the simplest iterative scheme: add the residual (difference between observed and predicted) directly to the current estimate. It is essentially the Jacobi method for solving linear systems applied to deconvolution.

### Math

Update rule:
\[
x_{k+1} = x_k + (g - h * x_k)
\]

Initial guess: \( x_0 = g \) (the observed spectrum).

### Frequency-domain view

After k iterations, the effective filter is a truncated geometric series:
\[
\hat{X}_k = G \cdot \frac{1 - (1 - H)^k}{H}
\]

As k → ∞, this tends to \( G/H \) (inverse filter) when \( |1-H| < 1 \). So Van Cittert approximates the inverse filter by a power series; early stopping acts as regularization.

### Parameters

- **Iterations**: Few (5–15). Convergence is slow after the first few steps, and the method is very sensitive to noise. More iterations → more noise amplification.

### Pros / Cons

| Pros | Cons |
|------|------|
| Very simple | Very noise-sensitive |
| No extra parameters | Slow convergence |
| Historical baseline | Not recommended alone |
| Easy to implement | |

### Why it’s rarely used alone

The residual \( g - h*x_k \) contains both (a) signal that hasn’t been recovered yet and (b) noise. Van Cittert adds the full residual, so noise is repeatedly re-injected. Constrained variants (e.g. Jansson) damp the residual to reduce this effect.

---

## 4. Jansson Deconvolution (Constrained Van Cittert)

### Idea

Jansson (1968–1970) extends Van Cittert by multiplying the residual by a *relaxation function* that depends on the current estimate. The function is chosen so that updates are suppressed when the estimate is near its physical limits (0 or maximum value), which reduces noise-driven corrections.

### Math

Update rule:
\[
x^{k+1} = x^k + r(x^k) \cdot \left[ g - h * x^k \right]
\]

Relaxation function:
\[
r(x) = b \left(1 - \frac{2}{c}\left|x - \frac{c}{2}\right|\right)
\]

- **b**: Relaxation constant (typically 0.5–1.0). Controls overall step size.
- **c**: Maximum peak amplitude. Enforces the prior that the true spectrum lies in [0, c].

The function r(x) is largest when x ≈ c/2 (mid-range) and goes to 0 as x → 0 or x → c. So corrections are strong in the middle of the dynamic range and weak near the bounds, which helps avoid non-physical values and dampens noise-driven updates at extremes.

### Parameters

- **b**: 0.5–1.0. Higher → faster convergence, more noise risk.
- **c**: Max amplitude. Estimate from `np.percentile(signal, 99)` or `np.max(signal)`, or set by user.
- **Iterations**: Often 50–200 in chromatography; for spectra, start with 20–50.

### Applications

Used in gas chromatography and spectroscopy to resolve severely overlapped peaks without needing the number of peaks in advance. Only requires the impulse response (PSF) and an estimate of maximum amplitude.

### Pros / Cons

| Pros | Cons |
|------|------|
| Incorporates physical bounds [0, c] | Needs good estimate of c |
| Better noise behavior than plain Van Cittert | More iterations than Wiener/Tikhonov |
| No need to know number of peaks | b and c need tuning |
| Validated in chromatography/spectroscopy | |

### Implementation sketch

```python
def jansson_relaxation(x, c, b=1.0):
    return b * (1 - (2/c) * np.abs(x - c/2))

c = np.percentile(signal, 99)  # or user-provided
x = signal.copy().astype(np.float64)
for _ in range(num_iter):
    residual = signal - np.convolve(x, psf, mode='same')
    r = jansson_relaxation(x, c, b)
    x = x + r * residual
    x = np.clip(x, 0, c)
```

---

## 5. Gold Algorithm

### Idea

Gold’s algorithm is a variant of Van Cittert with a *variable* relaxation factor that changes each iteration or per pixel. The relaxation is chosen to speed up convergence while trying to avoid the instability that comes from boosting the residual in plain Van Cittert.

### Math

Same structure as Van Cittert:
\[
x_{k+1} = x_k + \alpha_k \cdot (g - h * x_k)
\]

but α_k is chosen adaptively. One common form: α varies so that the update is scaled by a factor that depends on the current estimate and the residual. Different formulations exist in the literature.

### Relation to Van Cittert

Gold can be viewed as Van Cittert with a variable relaxation factor. The algebraic analysis in JOSA 11(11), 2804 (1994) shows that Gold’s variable factor can remove linear instability present in fixed-step Van Cittert for certain system matrices.

### Applications

Used in gamma-ray spectroscopy and similar applications where instrument response can introduce linear instabilities. Less commonly used in optical spectroscopy than Jansson or Landweber.

### Pros / Cons

| Pros | Cons |
|------|------|
| Can improve convergence over Van Cittert | Multiple formulations, less standardized |
| May reduce linear instability | More complex to implement and tune |
| | Lower priority for spectrometer use |

---

## 6. Comparison Summary

| Technique | Type | Key parameter(s) | Cost | Noise behavior |
|-----------|------|------------------|------|----------------|
| **Tikhonov** | Non-iterative | λ | O(N log N) | Safer; λ controls smoothing |
| **Landweber** | Iterative | ω, iterations | O(N × iter) | Semi-convergent; stop early |
| **Van Cittert** | Iterative | iterations | O(N × iter) | Very noise-sensitive |
| **Jansson** | Iterative, constrained | b, c, iterations | O(N × iter) | Safer; bounds constrain updates |
| **Gold** | Iterative | variable α | O(N × iter) | Medium; formulation-dependent |

---

## 7. References

- Tikhonov: Standard inverse problems literature; ESO MIDAS docs (multiresolution Tikhonov).
- Landweber: Landweber (1951) Amer. J. Math.; Wikipedia “Landweber iteration”; Hanke et al. Numer. Math. 72, 21 (1995).
- Van Cittert: Van Cittert (1931); STSci iterative deconvolution notes (Coggins).
- Jansson: Jansson, *Deconvolution With Applications in Spectroscopy* (1984); Crilly, J. Res. NBS 93, 413 (1988); PMC5181942.
- Gold: JOSA 11(11), 2804 (1994); gamma-ray spectroscopy literature.

---

## 8. Document History

- **Created**: 2025-03-17 — Elaboration for learning; complements SIGNAL_PROCESSING_RESEARCH.md §3.1.4.
