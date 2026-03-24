# -*- coding: utf-8 -*-
"""
Spectrometer Optical Path Simulator

Interactive simulation of spectrometer optical elements:
- Entrance slit, collimation, diffraction grating (reflective/transmissive), camera, detector.

Features:
- Geometrically accurate layout in mm (Czerny-Turner); print at 100% and verify 50 mm scale bar.
- Transmissive grating: rays pass through; reflective: rays reflect. Grating tilted by θᵢ.
- Light intensity: throughput curve (mirror reflectivity × grating efficiency vs λ) on spectrum plot.

Equations from spectrometer/docs/OPTICAL_EQUATIONS.md
"""

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Slider, RadioButtons
from matplotlib.patches import FancyBboxPatch, Circle, Arc
from matplotlib.collections import LineCollection

# ========== OPTICAL EQUATIONS ==========

def grating_diffraction_angle(lam_nm: float, grooves_per_mm: float, theta_i_rad: float, m: int) -> float | None:
    """
    Grating equation: m*λ = d*(sin α + sin β)  =>  β = arcsin(mλ/d - sin α)
    Returns diffraction angle in radians, or None if |sin β| > 1.
    """
    lam_m = lam_nm * 1e-9
    d = 1e-3 / grooves_per_mm
    sin_beta = (m * lam_m / d) - np.sin(theta_i_rad)
    if abs(sin_beta) > 1:
        return None
    return np.arcsin(sin_beta)


def pixel_from_wavelength(lam_nm: float, grooves_per_mm: float, theta_i_rad: float,
                         f_cam_mm: float, beta0_rad: float, p0: float, m: int,
                         pixel_size_um: float = 14.0) -> float | None:
    """
    Map wavelength to pixel position: p = p0 + f_cam * tan(β - β0)
    Returns pixel index (float), or None if wavelength not diffracted.
    """
    beta = grating_diffraction_angle(lam_nm, grooves_per_mm, theta_i_rad, m)
    if beta is None:
        return None
    f_m = f_cam_mm * 1e-3
    p_mm = p0 + f_m * 1e3 * np.tan(beta - beta0_rad)
    return p_mm * 1000 / pixel_size_um  # pixels


def resolution_diffraction_limit(lam_nm: float, N: int, m: int) -> float:
    """Δλ = λ / (N*m) in nm."""
    return lam_nm / (N * m)


def resolution_slit_limit(grooves_per_mm: float, slit_width_um: float,
                         f_coll_mm: float, m: int) -> float:
    """Δλ ≈ d * Δx / (f * m) in nm. Approximate."""
    d_m = 1e-3 / grooves_per_mm
    return d_m * (slit_width_um * 1e-6) / (f_coll_mm * 1e-3 * m) * 1e9


def grating_efficiency(lam_nm: float, blaze_nm: float = 500) -> float:
    """Simplified grating efficiency vs wavelength (Littrow approximation). Peak at blaze."""
    return 0.5 + 0.4 * np.exp(-((lam_nm - blaze_nm) / 150) ** 2)


def optical_throughput(lam_nm: float, mirror_reflectivity: float = 0.95,
                       blaze_nm: float = 500) -> float:
    """Relative throughput: mirrors × grating. Slit étendue omitted (geometry-dependent)."""
    return mirror_reflectivity ** 2 * grating_efficiency(lam_nm, blaze_nm)


# ========== RAY DRAWING ==========

def ray_2d(ax, origin, angle_rad, length, color, lw=2, alpha=1.0, label=None):
    """Draw a ray from origin at angle (from vertical/y-axis)."""
    dx = length * np.sin(angle_rad)
    dy = length * np.cos(angle_rad)
    ax.plot([origin[0], origin[0] + dx], [origin[1], origin[1] + dy],
            color=color, lw=lw, alpha=alpha, label=label)


def draw_grating(ax, x, y, width, height, grating_type="reflective", tilt_rad=0):
    """Draw grating as ruled surface. tilt_rad = angle of grating normal from vertical."""
    from matplotlib.patches import Polygon
    c, s = np.cos(tilt_rad), np.sin(tilt_rad)
    corners = np.array([[-width/2, -height/2], [width/2, -height/2], [width/2, height/2], [-width/2, height/2]])
    corners = corners @ np.array([[c, -s], [s, c]]).T + [x, y]
    poly = Polygon(corners, facecolor='#e8e8e8' if grating_type == 'transmissive' else '#e0e0e0',
                   edgecolor='#333', linewidth=1.5)
    ax.add_patch(poly)
    n_grooves = min(20, max(5, int(width / 2)))
    for i in range(n_grooves):
        gx_loc = -width/2 + (i + 0.5) * width / n_grooves
        cx, cy = x + gx_loc * c, y + gx_loc * s
        ax.plot([cx - s * height/2, cx + s * height/2], [cy + c * height/2, cy - c * height/2], 'k-', lw=0.4, alpha=0.7)
    label = grating_type[0].upper() + grating_type[1:]
    ax.text(x + s * (height/2 + 2), y + c * (height/2 + 2), label, ha='center', fontsize=7)


def draw_concave_mirror(ax, vertex_x, vertex_y, focal_mm, aperture_mm, facing='left'):
    """Draw concave mirror arc. vertex = mirror center; R=2*focal. facing: 'left' or 'right'."""
    R = 2 * focal_mm
    theta_span_deg = min(50, 2 * np.degrees(np.arcsin(np.clip(aperture_mm / (2 * R), 0, 1))))
    if facing == 'left':
        center_x = vertex_x - R
        theta1, theta2 = -theta_span_deg/2, theta_span_deg/2
    else:
        center_x = vertex_x + R
        theta1, theta2 = 180 - theta_span_deg/2, 180 + theta_span_deg/2
    arc = Arc((center_x, vertex_y), 2*R, 2*R, theta1=theta1, theta2=theta2,
              lw=2, color='#444', fill=False)
    ax.add_patch(arc)


# ========== COMMERCIAL CONSTRAINTS ==========
# Discrete values matching typical commercial availability (Thorlabs, Edmund, Avantes, Sarspec)

GROOVES_PER_MM_OPTIONS = [400, 600, 900, 1200, 1800, 2400]  # gratings
SLIT_WIDTH_UM_OPTIONS = [10, 25, 50, 100, 200]               # entrance slits
SENSOR_RESOLUTION_OPTIONS = [512, 1024, 2048, 4096]  # detector pixels
PIXEL_SIZE_UM_OPTIONS = [2.7, 7, 10, 14, 24]       # pixel pitch

# ========== FIGURE SETUP ==========

fig, (ax_rays, ax_spectrum) = plt.subplots(1, 2, figsize=(12, 6))
plt.subplots_adjust(bottom=0.42, left=0.06, right=0.96)
ax_spectrum_twin = ax_spectrum.twinx()

# Default parameters (must be in OPTIONS for discrete sliders)
params = {
    "grooves_per_mm": 1200,
    "lambda1_nm": 700,
    "lambda2_nm": 400,
    "theta_i_deg": 15,
    "f_coll_mm": 40,
    "f_cam_mm": 30,
    "slit_width_um": 200,
    "grating_type": "reflective",
    "N_grooves": 50000,
    "sensor_resolution": 1024,
    "pixel_size_um": 2.7,
}

# Sliders: left column (optical params), right column (geometry + sensor)
ax_grooves = plt.axes([0.18, 0.30, 0.32, 0.02])
ax_lam1 = plt.axes([0.18, 0.26, 0.32, 0.02])
ax_lam2 = plt.axes([0.18, 0.22, 0.32, 0.02])
ax_theta = plt.axes([0.18, 0.18, 0.32, 0.02])
ax_fcoll = plt.axes([0.58, 0.30, 0.32, 0.02])
ax_fcam = plt.axes([0.58, 0.26, 0.32, 0.02])
ax_slit = plt.axes([0.58, 0.22, 0.32, 0.02])
ax_sensor_res = plt.axes([0.58, 0.18, 0.32, 0.02])
ax_pixel_size = plt.axes([0.58, 0.14, 0.32, 0.02])

s_grooves = Slider(ax_grooves, "Grooves/mm", GROOVES_PER_MM_OPTIONS[0], GROOVES_PER_MM_OPTIONS[-1],
                   valinit=params["grooves_per_mm"], valstep=GROOVES_PER_MM_OPTIONS)
s_lam1 = Slider(ax_lam1, "λ₁ [nm]", 350, 900, valinit=params["lambda1_nm"])
s_lam2 = Slider(ax_lam2, "λ₂ [nm]", 350, 900, valinit=params["lambda2_nm"])
s_theta = Slider(ax_theta, "θᵢ [°]", 0, 80, valinit=params["theta_i_deg"])
s_fcoll = Slider(ax_fcoll, "f_coll [mm]", 20, 100, valinit=params["f_coll_mm"])
s_fcam = Slider(ax_fcam, "f_cam [mm]", 30, 120, valinit=params["f_cam_mm"])
s_slit = Slider(ax_slit, "Slit [µm]", SLIT_WIDTH_UM_OPTIONS[0], SLIT_WIDTH_UM_OPTIONS[-1],
                valinit=params["slit_width_um"], valstep=SLIT_WIDTH_UM_OPTIONS)
s_sensor_res = Slider(ax_sensor_res, "Sensor px", SENSOR_RESOLUTION_OPTIONS[0], SENSOR_RESOLUTION_OPTIONS[-1],
                      valinit=params["sensor_resolution"], valstep=SENSOR_RESOLUTION_OPTIONS)
s_pixel_size = Slider(ax_pixel_size, "Pixel [µm]", PIXEL_SIZE_UM_OPTIONS[0], PIXEL_SIZE_UM_OPTIONS[-1],
                      valinit=params["pixel_size_um"], valstep=PIXEL_SIZE_UM_OPTIONS)

ax_radio = plt.axes([0.02, 0.08, 0.12, 0.06])
radio = RadioButtons(ax_radio, ("reflective", "transmissive"), active=0)
grating_type_var = ["reflective"]  # mutable for callback
intensity_var = [True]  # show throughput curve


# ========== UPDATE ==========

def update(_=None):
    """Redraw the optical path and spectrum panels using current slider values.

    Inputs:
        _: Unused callback parameter provided by matplotlib (`on_changed`/`on_clicked`).
    Output:
        None (side-effect: clears and repopulates matplotlib axes).
    Transformation:
        Reads slider values (grooves density, wavelengths, incident angle, focal lengths, slit, sensor params,
        grating type), then:
        - draws a geometrically accurate layout in millimeters,
        - computes diffraction mapping from wavelength to detector pixel indices,
        - optionally draws a throughput/intensity curve.
    """
    ax_rays.cla()
    ax_spectrum.cla()

    grooves = int(s_grooves.val)
    lam1 = s_lam1.val
    lam2 = s_lam2.val
    theta_i = np.deg2rad(s_theta.val)
    f_coll = s_fcoll.val
    f_cam = s_fcam.val
    slit = int(s_slit.val)
    sensor_res = int(s_sensor_res.val)
    pixel_size_um = int(s_pixel_size.val)
    gtype = grating_type_var[0]

    # ========== GEOMETRICALLY ACCURATE LAYOUT (mm) ==========
    # Czerny-Turner: slit @ f_coll from collimator; collimator→grating; grating→camera; detector @ f_cam from camera
    d_coll_grating = f_coll   # collimated beam distance
    d_grating_cam = f_cam    # diffracted beam to camera

    x_slit = 0
    x_coll = f_coll
    x_grating = f_coll + d_coll_grating
    x_camera = x_grating + d_grating_cam
    x_detector = x_camera + f_cam

    # Component sizes (mm)
    slit_h_mm = slit / 1000
    grating_w, grating_h = 25, 12
    detector_h_mm = sensor_res * pixel_size_um / 1000
    mirror_aperture = 25

    # Slit (entrance at origin)
    ax_rays.plot([x_slit, x_slit], [-slit_h_mm/2, slit_h_mm/2], 'k-', lw=3, label='Slit')
    ax_rays.text(x_slit - 5, 0, f'Slit {slit} µm', fontsize=7, ha='right', va='center')

    # Collimator mirror (vertex at f_coll from slit, concave, faces slit)
    draw_concave_mirror(ax_rays, x_coll, 0, f_coll, mirror_aperture, facing='left')
    ax_rays.text(x_coll + 3, 12, f'Collimator f={f_coll:.0f}mm', fontsize=7, ha='left')

    # Collimated beam from collimator to grating (incident angle θᵢ from normal)
    ray_2d(ax_rays, (x_coll, 0), theta_i, d_coll_grating, 'gray', lw=1.5, alpha=0.8, label='Incident')

    # Grating (tilted by θᵢ; transmissive = rays pass through)
    draw_grating(ax_rays, x_grating, 0, grating_w, grating_h, gtype, tilt_rad=theta_i)
    ax_rays.text(x_grating + grating_w/2 + 2, 1, f'θ={np.degrees(theta_i):.0f}°', fontsize=6)

    # Diffracted rays (m=1): converge to detector pixels (via camera mirror)
    for lam, color, lbl in [(lam1, 'red', f'λ={lam1:.0f}nm'), (lam2, 'blue', f'λ={lam2:.0f}nm')]:
        beta = grating_diffraction_angle(lam, grooves, theta_i, 1)
        if beta is not None:
            px = pixel_from_wavelength(lam, grooves, theta_i, f_cam, 0, 0, 1, pixel_size_um)
            if px is not None:
                y_det = (px - sensor_res / 2) * pixel_size_um / 1000
                ax_rays.plot([x_grating, x_detector], [0, np.clip(y_det, -detector_h_mm/2 + 0.5, detector_h_mm/2 - 0.5)], color=color, lw=2, label=lbl)

    # Camera mirror (vertex at x_camera, concave, faces detector)
    draw_concave_mirror(ax_rays, x_camera, 0, f_cam, mirror_aperture, facing='right')
    ax_rays.text(x_camera - 3, 12, f'Camera f={f_cam:.0f}mm', fontsize=7, ha='right')

    # Detector (at focal plane of camera)
    ax_rays.plot([x_detector, x_detector], [-detector_h_mm/2, detector_h_mm/2], 'g-', lw=3, alpha=0.6, label='Detector')
    ax_rays.text(x_detector + 5, 0, f'Detector {sensor_res}×{pixel_size_um}µm', fontsize=7, ha='left', va='center')

    # Axes in mm, equal aspect for scale accuracy (print at 100% for 1:1 mm scale)
    margin_x, margin_y = 15, 25
    ax_rays.set_xlim(-margin_x, x_detector + margin_x)
    ax_rays.set_ylim(-detector_h_mm/2 - margin_y, detector_h_mm/2 + margin_y)
    ax_rays.set_aspect('equal')
    ax_rays.set_xlabel('Optical axis [mm]')
    ax_rays.set_ylabel('Transverse [mm]')
    ax_rays.grid(True, alpha=0.3, linestyle='--')
    ax_rays.legend(loc='upper left', bbox_to_anchor=(-0.02, 1.0), fontsize=7, framealpha=0.9)
    ax_rays.set_title('Optical path (slit → collimator → grating → camera → detector) — scale in mm')

    # Dimension annotations (for print layout)
    def dim_line(ax, x1, x2, y, label):
        """Draw a dimension line with a label between two x-coordinates.

        Inputs:
            ax: Matplotlib axis.
            x1, x2: Start/end x-coordinates (mm).
            y: Baseline y-coordinate used to place the dimension label.
            label: Text to render next to the dimension.
        Output:
            None (side-effect: draws lines/text on `ax`).
        Transformation:
            Plots a small “┐┘” style dimension marker and writes `label` near the midpoint.
        """
        ax.plot([x1, x1, x2, x2], [y, y-2, y-2, y], 'k-', lw=0.8)
        ax.text((x1+x2)/2, y-4, label, fontsize=6, ha='center')
    dim_line(ax_rays, x_slit, x_coll, -detector_h_mm/2 - 8, f'{f_coll:.0f}')
    dim_line(ax_rays, x_coll, x_grating, -detector_h_mm/2 - 8, f'{d_coll_grating:.0f}')
    dim_line(ax_rays, x_grating, x_camera, -detector_h_mm/2 - 8, f'{d_grating_cam:.0f}')
    dim_line(ax_rays, x_camera, x_detector, -detector_h_mm/2 - 8, f'{f_cam:.0f}')

    # Scale bar
    scale_len = 50
    ax_rays.plot([x_detector - scale_len - 10, x_detector - 10], [-detector_h_mm/2 - 18, -detector_h_mm/2 - 18], 'k-', lw=2)
    ax_rays.text(x_detector - scale_len/2 - 10, -detector_h_mm/2 - 22, f'{scale_len} mm (print scale)', fontsize=6, ha='center')

    # Spectrum panel: pixel vs wavelength (uses pixel_size_um)
    wavelengths = np.linspace(350, 900, 200)
    beta0 = 0
    p0 = 0
    pixels = []
    for wl in wavelengths:
        px = pixel_from_wavelength(wl, grooves, theta_i, f_cam, beta0, p0, 1, pixel_size_um)
        pixels.append(px if px is not None else np.nan)
    pixels = np.array(pixels)
    valid = ~np.isnan(pixels)
    if np.any(valid):
        ax_spectrum.plot(wavelengths[valid], pixels[valid], 'b-', lw=2, label='p(λ)')
    ax_spectrum.axvline(lam1, color='red', alpha=0.5, ls='--')
    ax_spectrum.axvline(lam2, color='blue', alpha=0.5, ls='--')

    # Throughput / intensity (optional)
    ax_spectrum_twin.cla()
    if intensity_var[0]:
        throughput = optical_throughput(wavelengths)
        ax_spectrum_twin.fill_between(wavelengths, 0, throughput, alpha=0.2, color='orange')
        ax_spectrum_twin.plot(wavelengths, throughput, 'orange', lw=1.5, alpha=0.8, label='Throughput')
        ax_spectrum_twin.set_ylabel('Relative intensity', fontsize=8, color='orange')
        ax_spectrum_twin.set_ylim(0, 1.1)
        ax_spectrum_twin.tick_params(axis='y', labelcolor='orange', labelsize=7)
        ax_spectrum_twin.set_visible(True)
    else:
        ax_spectrum_twin.set_visible(False)
    ax_spectrum.set_xlabel('Wavelength [nm]')
    ax_spectrum.set_ylabel('Pixel index')
    ax_spectrum.set_title('Wavelength–pixel mapping')
    ax_spectrum.legend(loc='upper left', fontsize=9, framealpha=0.9)
    ax_spectrum.grid(True, alpha=0.3)

    # Highlight valid sensor pixel range (0 to sensor_res-1)
    ax_spectrum.axhspan(0, sensor_res, alpha=0.06, color='green', zorder=0)

    # Resolution info (lower right to avoid legend overlap)
    dlam_diff = resolution_diffraction_limit(550, params["N_grooves"], 1)
    dlam_slit = resolution_slit_limit(grooves, slit, f_coll, 1)
    info = (f'dλ_diff~{dlam_diff:.3f} nm  dλ_slit~{dlam_slit:.2f} nm\n'
            f'sensor={sensor_res} px  pixel={pixel_size_um} µm')
    ax_spectrum.text(0.98, 0.02, info,
                     transform=ax_spectrum.transAxes, fontsize=7, va='bottom', ha='right',
                     bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    fig.canvas.draw_idle()


# ========== WIRING ==========

for s in (s_grooves, s_lam1, s_lam2, s_theta, s_fcoll, s_fcam, s_slit, s_sensor_res, s_pixel_size):
    s.on_changed(update)
def on_radio(label):
    """Handle grating type selection from radio buttons.

    Inputs:
        label: Selected grating type string (e.g. "reflective" or "transmissive").
    Output:
        None (side-effect: updates grating type state and triggers redraw).
    Transformation:
        Updates `grating_type_var[0]` and calls `update()` to re-render the simulation.
    """
    grating_type_var[0] = label
    update()
radio.on_clicked(on_radio)

update()
plt.show()
