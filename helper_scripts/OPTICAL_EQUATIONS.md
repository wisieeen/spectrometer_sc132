# Spectrometer Optical Equations and Rules

**Purpose**: Reference for optical path design, diffraction gratings (reflective/transmissive), and collimation. Used by optical simulator and ML optimizer.

---

## 1. Grating Equation (Universal)

Constructive interference for both **reflective** and **transmissive** gratings:

$$m\lambda = d(\sin\alpha + \sin\beta)$$


| Symbol  | Meaning                                                         |
| ------- | --------------------------------------------------------------- |
| m       | Diffraction order (integer: 0, ±1, ±2, …)                       |
| \lambda | Wavelength                                                      |
| d       | Groove spacing (d = 1/\sigma, \sigma = grooves per unit length) |
| \alpha  | Incident angle (from grating normal)                            |
| \beta   | Diffraction angle (from grating normal)                         |


**Sign convention**: \alpha and \beta on same side of normal → same sign; opposite sides → opposite sign. For Littrow: \alpha = \beta.

---

## 2. Reflective vs Transmissive Gratings


| Type             | Geometry                          | Notes                                                    |
| ---------------- | --------------------------------- | -------------------------------------------------------- |
| **Reflective**   | Light reflects from ruled surface | Common in spectrometers; blaze angle improves efficiency |
| **Transmissive** | Light passes between rulings      | Same equation; path difference in transmission           |


Both use the same grating equation. Difference is physical layout, not math.

---

## 3. Collimation

**Rule**: Entrance slit at focal plane of collimator → parallel (collimated) beam at grating.

- **Thin lens**: Object at f → image at ∞ → rays parallel.
- **Concave mirror**: Object at focal plane → reflected rays parallel.

**Far-field condition**: Grating diffraction assumes plane waves. Collimation ensures this.

---

## 4. Czerny–Turner Layout (Typical Spectrometer)

1. **Entrance slit** → at focal plane of collimator mirror
2. **Collimator** → produces collimated beam
3. **Grating** → disperses by wavelength
4. **Camera mirror** → focuses dispersed rays onto detector
5. **Detector** → at focal plane of camera mirror

**Pixel–wavelength mapping** (camera focal length f_{\text{cam}}, reference angle \beta_0):

$$p = p_0 + f_{\text{cam}} \tan\left[\arcsin\left(\frac{m\lambda}{\sigma} - \sin\alpha\right) - \beta_0\right]$$

---

## 5. Resolution

### Diffraction limit (narrow slit)

$$\Delta\lambda = \frac{\lambda}{Nm}$$

Resolving power: R = \lambda/\Delta\lambda = Nm (N = illuminated grooves).

### Slit-limited resolution

$$\Delta\lambda \approx \frac{d\Delta x}{fm}$$

\Delta x = slit width, f = collimator focal length.

**Slit for diffraction limit**: \Delta x \lesssim \frac{f\lambda}{Nd}

---

## 6. Angular Dispersion

$$\frac{d\beta}{d\lambda} = \frac{m}{\sigma\cos\beta}$$

Higher m or smaller \sigma → larger angular spread.

---

## 7. Order Overlap

Different orders can overlap: m_1\lambda_1 = m_2\lambda_2. Use order-sorting filters to block unwanted orders.

---

## 8. Summary for Simulator


| Quantity          | Formula                                       |
| ----------------- | --------------------------------------------- |
| Groove spacing    | d = 1/\sigma (e.g. \sigma in mm⁻¹)            |
| Diffraction angle | \beta = \arcsin(m\lambda/\sigma - \sin\alpha) |
| Pixel position    | p = p_0 + f\tan(\beta - \beta_0)              |
| Diffraction limit | \Delta\lambda = \lambda/(Nm)                  |
| Slit limit        | \Delta\lambda \approx d\Delta x/(fm)          |


---

## 9. Related

- [spectrometer_optical_simulator.py](spectrometer_optical_simulator.py) - interactive ray diagram
- [../spectrometer/docs/CODER_INSTRUCTIONS.md](../spectrometer/docs/CODER_INSTRUCTIONS.md) - implementation notes for optical tools

