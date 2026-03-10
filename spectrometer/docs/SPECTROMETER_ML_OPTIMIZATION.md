# ML Techniques for Spectrometer Geometry Optimization
## this part is actually untested after being AI generated
**Purpose**: Evaluate ML/optimization methods for finding optimal optical geometry. Two techniques implemented; four evaluated.

**Related**: [OPTICAL_EQUATIONS.md](OPTICAL_EQUATIONS.md) (grating, resolution), [CODER_INSTRUCTIONS.md](CODER_INSTRUCTIONS.md) (run `spectrometer_ml_optimizer.py`).

---

## 1. Four Candidate Techniques

| Technique | Pros | Cons | Best for |
|-----------|------|------|----------|
| **Bayesian Optimization** | Sample-efficient, handles noisy black-box | GP scaling with dims | Expensive objectives, few evaluations |
| **Genetic Algorithm** | Proven in optical design, multimodal | Many evaluations | Complex landscapes, constraints |
| **Particle Swarm (PSO)** | Simple, no gradients | Can stagnate | Medium-dim, smooth objectives |
| **Gradient-based (L-BFGS)** | Fast convergence | Needs differentiable objective | Smooth, convex-like objectives |

---

## 2. Two Implemented (Most Promising)

### 2.1 Bayesian Optimization (gp_minimize)

- **Library**: scikit-optimize (`skopt`)
- **Model**: Gaussian Process surrogate
- **Acquisition**: Expected Improvement (EI)
- **Use when**: Objective is expensive (e.g. ray tracing); budget 20–100 evaluations

### 2.2 Genetic Algorithm (Differential Evolution)

- **Library**: scipy.optimize.differential_evolution
- **Variant**: Evolutionary strategy (mutation, crossover, selection)
- **Use when**: Multimodal, non-differentiable; budget 100–500 evaluations

---

## 3. Objective Function (Merit)

Default: **maximize effective resolution** (minimize Δλ) while keeping spectral range.

$$M = -\frac{\Delta\lambda_{\text{eff}}}{\lambda_{\text{center}}} - w \cdot \text{penalty}(\text{range})$$

Or: minimize weighted sum of resolution and range penalty.

---

## 4. Design Variables (Bounds)

| Variable | Min | Max | Unit |
|----------|-----|-----|------|
| grooves_per_mm | 300 | 2400 | mm⁻¹ |
| theta_i | 10 | 70 | deg |
| f_coll | 25 | 80 | mm |
| f_cam | 40 | 100 | mm |
| slit_width_um | 15 | 80 | µm |

---

## 5. Dependencies

```
scipy>=1.7.0
scikit-optimize>=0.9.0
```

Add to requirements.txt when using ML optimizer.
