#!/usr/bin/env python3
"""
Spectrometer calibration wizard. Interactive UI for line selection and wavelength calibration.
Runs on a device with display (not the headless sensor). Load preview image, define line,
click spectrum to add calibration pairs, save config.
"""
from __future__ import annotations

import argparse
import os
import sys

import cv2
import matplotlib.pyplot as plt
import matplotlib.widgets as widgets
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.config import (
    DEFAULT_SPECTROMETER_CONFIG,
    load_spectrometer_config,
    save_spectrometer_config,
)
from lib.spectrum import extract_line_profile, fit_calibration

SPECTRUM_DEBOUNCE_MS = 300
WL_MIN_NM = 200.0
WL_MAX_NM = 1200.0
# Vertical spacing between lines in the calibration list panel (axes coordinates)
LIST_LINE_STEP = 0.095

# Hardcoded calibration lamp wavelength reference lines (nm).
LAMP_LIBRARY: dict[str, list[float]] = {
    # Common Ne lamp lines (nm)
    "Neon": [585.249,614.306,640.225,650.653,667.828,692.947,703.241],
}


def parse_reference_wavelengths(text: str) -> list[float]:
    """Parse comma/semicolon/whitespace-separated reference wavelengths (nm)."""
    if not text or not text.strip():
        return []
    out: list[float] = []
    for part in text.replace(";", ",").replace(" ", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            v = float(part)
        except ValueError:
            continue
        if WL_MIN_NM <= v <= WL_MAX_NM:
            out.append(v)
    return out


def find_calibration_peaks(y: np.ndarray, n_peaks: int, min_distance: int | None = None) -> np.ndarray:
    """
    Return up to n_peaks sub-pixel peak positions (float pixel indices) along the profile,
    greedy by prominence (simple left/right minima), enforcing minimum separation.
    """
    y = np.asarray(y, dtype=np.float64)
    n = int(y.size)
    if n < 3 or n_peaks < 1:
        return np.array([], dtype=np.float64)
    if min_distance is None:
        min_distance = max(3, n // 200)
    min_distance = max(1, min_distance)

    local_idx: list[int] = []
    for i in range(1, n - 1):
        if y[i] >= y[i - 1] and y[i] > y[i + 1]:
            local_idx.append(i)
        elif y[i] > y[i - 1] and y[i] == y[i + 1]:
            j = i
            while j + 1 < n and y[j + 1] == y[i]:
                j += 1
            if j + 1 < n and y[j + 1] < y[i]:
                local_idx.append((i + j) // 2)

    if not local_idx:
        return np.array([], dtype=np.float64)

    idx_arr = np.array(local_idx, dtype=int)
    prom = np.empty(len(idx_arr), dtype=np.float64)
    for k, i in enumerate(idx_arr):
        lo = max(0, i - min_distance * 3)
        hi = min(n - 1, i + min_distance * 3)
        left_min = float(np.min(y[lo:i])) if i > lo else float(y[i])
        right_min = float(np.min(y[i + 1 : hi + 1])) if i < hi else float(y[i])
        prom[k] = float(y[i]) - max(left_min, right_min)

    base = float(np.percentile(y, 20))
    span = float(np.max(y) - base)
    min_prom = max(span * 0.03, 1e-9)
    keep = prom >= min_prom
    idx_arr = idx_arr[keep]
    prom = prom[keep]
    if len(idx_arr) == 0:
        i_max = int(np.argmax(y))
        return np.array([float(i_max)], dtype=np.float64) if n_peaks == 1 else np.array([], dtype=np.float64)

    order = np.argsort(-prom)
    chosen: list[int] = []
    for o in order:
        p = int(idx_arr[o])
        if all(abs(p - q) >= min_distance for q in chosen):
            chosen.append(p)
        if len(chosen) >= n_peaks:
            break

    if len(chosen) < n_peaks:
        return np.array([], dtype=np.float64)
    chosen.sort()
    return np.array([float(p) for p in chosen[:n_peaks]], dtype=np.float64)


def _rss_calibration(
    pair_tuples: list[tuple[float, float]],
    fit_type: str,
    poly_degree: int,
) -> float:
    """Residual sum of squares for λ vs pixel fit."""
    px = np.array([p[0] for p in pair_tuples], dtype=np.float64)
    wl = np.array([p[1] for p in pair_tuples], dtype=np.float64)
    coeffs = fit_calibration(pair_tuples, fit_type, poly_degree)
    pred = np.polyval(coeffs, px)
    return float(np.sum((wl - pred) ** 2))


def auto_calibration_pairs(
    intensities: np.ndarray,
    ref_wavelengths_nm: list[float],
    fit_type: str,
    poly_degree: int,
) -> tuple[list[list[float]], str]:
    """
    Detect peaks, assign reference wavelengths in increasing or decreasing order along pixels,
    pick the orientation with lower RSS. Returns (pairs as [px, wl], status message).
    """
    wls = sorted(set(float(w) for w in ref_wavelengths_nm))
    m = len(wls)
    if m < 2:
        return [], "Enter at least two reference wavelengths (comma-separated nm)."
    y = np.asarray(intensities, dtype=np.float64)
    if y.size < 5:
        return [], "Spectrum too short; check line ROI."

    peaks = find_calibration_peaks(y, m)
    if peaks.size < m:
        return (
            [],
            f"Found {int(peaks.size)} peak(s), need {m}. Adjust line/thickness or reference list.",
        )

    px_sorted = np.sort(peaks)
    asc = list(zip(px_sorted.tolist(), wls))
    desc = list(zip(px_sorted.tolist(), list(reversed(wls))))
    tup_a = [(float(a), float(b)) for a, b in asc]
    tup_b = [(float(a), float(b)) for a, b in desc]

    try:
        rss_a = _rss_calibration(tup_a, fit_type, poly_degree)
        rss_b = _rss_calibration(tup_b, fit_type, poly_degree)
    except ValueError as e:
        return [], f"Fit error: {e}"

    eps = 1e-9
    if rss_a < rss_b - eps:
        best = [[float(p), float(w)] for p, w in asc]
        note = "Auto: λ increases with pixel index (lower RSS)."
    elif rss_b < rss_a - eps:
        best = [[float(p), float(w)] for p, w in desc]
        note = "Auto: λ decreases with pixel index (lower RSS)."
    else:
        best = [[float(p), float(w)] for p, w in asc]
        note = "Auto: tie — assumed λ increases with pixel; verify or swap references."

    best.sort(key=lambda p: p[0])
    return best, note


def _default_image_path():
    """Choose a default preview image path to load.

    Inputs:
        None (checks known candidate paths on disk).
    Output:
        File path string to an existing image if found; otherwise returns the first candidate path.
    Transformation:
        Iterates over `candidates` and returns the first one that exists as a file.
    """
    candidates = [
        "spectrometer_preview.png",
        "/tmp/spectrometer_preview.png",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return candidates[0]


def _default_config_path():
    """Choose a default output config path for calibration results.

    Inputs:
        None (derives from script directory).
    Output:
        File path string pointing to `spectrometer_config.json` in the project root.
    Transformation:
        Computes `script_dir` and then returns `os.path.join(project_root, "spectrometer_config.json")`.
    """
    # Keep calibrate UI aligned with the project's single source of truth path.
    return DEFAULT_SPECTROMETER_CONFIG


def _normalize_channel_id(raw: str) -> str:
    """Normalize channel id text from CLI/UI for stable lookup."""
    return (raw or "").strip().lower() or "ch0"


def _find_channel_by_id(channels: list, raw_id: str):
    """Find channel by id with normalized matching (trim + lowercase)."""
    target = _normalize_channel_id(raw_id)
    return next((c for c in channels if _normalize_channel_id(c.get("id", "")) == target), None)


def main():
    """Interactive calibration wizard entrypoint (GUI with matplotlib).

    Inputs:
        Command-line args:
        - `--image`: optional path to the preview image
        - `--config`: optional output config path
        - `--channel-id`: channel id to update in the config
    Output:
        Saves updated spectrometer config on “Save” and updates on-screen displays while interacting.
    Transformation:
        Loads the preview image + existing config (if present), initializes channel/line/calibration state,
        renders the UI, and wires callbacks for:
        - selecting line endpoints on the image,
        - extracting/previewing spectrum slices,
        - adding/editing calibration pairs,
        - fitting calibration curves and saving results.
    """
    ap = argparse.ArgumentParser(description="Spectrometer calibration wizard (GUI)")
    ap.add_argument("--image", default=None, help="Preview image path")
    ap.add_argument("--config", default=None, help="Output config path")
    ap.add_argument(
        "--channel-id",
        default="ch0",
        help="Initial channel id to edit; switch channels in the UI without restarting",
    )
    args = ap.parse_args()

    image_path = args.image or _default_image_path()
    config_path = args.config or _default_config_path()

    if not os.path.isfile(image_path):
        print(f"Error: Image not found: {image_path}", file=sys.stderr)
        print("Run spectrometer_preview.py on the sensor, then SCP the image.", file=sys.stderr)
        sys.exit(1)

    frame = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if frame is None:
        print(f"Error: Failed to load image: {image_path}", file=sys.stderr)
        sys.exit(1)

    try:
        cfg = load_spectrometer_config(config_path)
    except FileNotFoundError:
        cfg = {"channels": [], "calibrations": []}

    channels = cfg.setdefault("channels", [])
    calibrations = cfg.setdefault("calibrations", [])

    channel = _find_channel_by_id(channels, args.channel_id)
    if channel is None:
        initial_channel_id = _normalize_channel_id(args.channel_id)
        channel = {
            "id": initial_channel_id,
            "line": {"start": [0, 0], "end": [frame.shape[1] - 1, frame.shape[0] // 2], "thickness": 5},
            "calibration_id": f"cal_{initial_channel_id}",
        }
        channels.append(channel)

    cal = next((c for c in calibrations if c["id"] == channel["calibration_id"]), None)
    if cal is None:
        cal = {"id": channel["calibration_id"], "pairs": [], "fit": "polynomial", "polynomial_degree": 2}
        calibrations.append(cal)

    line_start = list(channel["line"]["start"])
    line_end = list(channel["line"]["end"])
    thickness = channel["line"].get("thickness", 5)
    pairs: list[list[float]] = [list(p) for p in cal["pairs"]]
    fit_type = cal.get("fit", "polynomial")
    poly_degree = cal.get("polynomial_degree", 2)

    line_click_count = 0
    add_calibration_mode = False
    pending_pixel = None
    editing_index = None
    _skip_wl_submit = False
    show_wavelength_x = False

    spectrum_timer_ref: list = [None]
    tooltip_state = {"axes": None, "visible": False, "text": ""}
    suppress_slider_callback = [False]

    h, w = frame.shape
    fig = plt.figure(figsize=(14, 10))
    gs = fig.add_gridspec(
        5, 1,
        height_ratios=[2.2, 0.5, 1.5, 1, 0.9],
        left=0.02, right=0.98, top=0.96, bottom=0.24,
        hspace=0.15,
    )

    ax_img = fig.add_subplot(gs[0])
    ax_spec = fig.add_subplot(gs[2])
    ax_list = fig.add_subplot(gs[3])
    ax_btns = fig.add_subplot(gs[4])

    ax_img.set_title("Camera image — click two points to set line")
    ax_spec.set_title("Spectrum (intensity vs pixel) — click to add calibration point")
    ax_list.set_title("Calibration points")
    ax_img.set_axis_off()
    ax_list.set_axis_off()
    ax_btns.set_axis_off()

    # Line sliders: two full-width rows for higher precision.
    _row_h, _gap = 0.028, 0.006
    _y_x_row = 0.618
    _y_y_row = _y_x_row + _row_h + _gap
    ax_start_y = plt.axes([0.02, _y_y_row, 0.46, _row_h])
    ax_end_y = plt.axes([0.52, _y_y_row, 0.46, _row_h])
    ax_start_x = plt.axes([0.02, _y_x_row, 0.46, _row_h])
    ax_end_x = plt.axes([0.52, _y_x_row, 0.46, _row_h])

    _ch_y = _y_y_row + _row_h + 0.012
    ax_channel_id = plt.axes([0.02, _ch_y, 0.20, 0.028])
    ax_ch_apply = plt.axes([0.23, _ch_y, 0.07, 0.028])
    ax_ch_new = plt.axes([0.32, _ch_y, 0.11, 0.028])

    slider_start_y = widgets.Slider(ax_start_y, "Start Y", 0, h - 1, valinit=line_start[1], valstep=1)
    slider_end_y = widgets.Slider(ax_end_y, "End Y", 0, h - 1, valinit=line_end[1], valstep=1)
    slider_start_x = widgets.Slider(ax_start_x, "Start X", 0, w - 1, valinit=line_start[0], valstep=1)
    slider_end_x = widgets.Slider(ax_end_x, "End X", 0, w - 1, valinit=line_end[0], valstep=1)

    channel_id_box = widgets.TextBox(ax_channel_id, "Channel ", initial=channel["id"])
    btn_ch_apply = widgets.Button(ax_ch_apply, "Go")
    btn_ch_new = widgets.Button(ax_ch_new, "New channel")

    img_display = ax_img.imshow(frame, cmap="gray", aspect="auto")
    line_artist, = ax_img.plot([], [], "r-", linewidth=1)
    start_marker, = ax_img.plot([], [], "go", markersize=3)
    end_marker, = ax_img.plot([], [], "ro", markersize=3)

    ax_spec.set_aspect("auto")
    spec_line, = ax_spec.plot([], [], "b-", linewidth=1)
    cal_markers, = ax_spec.plot([], [], "r|", markersize=12)

    def _sync_sliders_to_line():
        """Synchronize line endpoint slider values to the current `line_start`/`line_end`.

        Inputs:
            None (uses `line_start` and `line_end` from the enclosing scope).
        Output:
            None (side-effect updates matplotlib slider widget values).
        Transformation:
            Writes the current endpoint pixel coordinates back into the slider widgets.
        """
        suppress_slider_callback[0] = True
        try:
            slider_start_x.set_val(line_start[0])
            slider_start_y.set_val(line_start[1])
            slider_end_x.set_val(line_end[0])
            slider_end_y.set_val(line_end[1])
        finally:
            suppress_slider_callback[0] = False

    def _flush_current_to_cfg():
        """Write current line, pairs, and fit from UI into the active channel and calibration dicts."""
        channel["line"] = {
            "start": [int(line_start[0]), int(line_start[1])],
            "end": [int(line_end[0]), int(line_end[1])],
            "thickness": thickness,
        }
        cal["pairs"] = [list(p) for p in pairs]
        cal["fit"] = fit_type
        cal["polynomial_degree"] = poly_degree
        if len(pairs) >= 2:
            try:
                cal["coefficients"] = fit_calibration(
                    [tuple(p) for p in pairs],
                    fit_type,
                    poly_degree,
                ).tolist()
            except ValueError:
                pass
        else:
            cal.pop("coefficients", None)

    def update_line_display():
        """Update the on-image line segment and start/end markers (no draw)."""
        line_artist.set_data([line_start[0], line_end[0]], [line_start[1], line_end[1]])
        start_marker.set_data([line_start[0]], [line_start[1]])
        end_marker.set_data([line_end[0]], [line_end[1]])

    def _coeffs_for_current_pairs():
        if len(pairs) < 2:
            return None
        return fit_calibration([tuple(p) for p in pairs], fit_type, poly_degree)

    def _wavelength_to_pixel(wl: float, coeffs: np.ndarray, n_pixels: int) -> float:
        """Convert a wavelength value back into a pixel index using calibration coefficients.

        Inputs:
            wl: Wavelength in nm.
            coeffs: Calibration coefficients for the selected `fit_type`.
            n_pixels: Total number of pixels in the spectrum.
        Output:
            Pixel index as float (best-effort even when polynomial inversion has no valid root).
        Transformation:
            Solves the inverse mapping (linear algebra for linear fits, root selection/nearest-value for polynomial fits).
        """
        if fit_type == "linear" and len(coeffs) == 2:
            if abs(coeffs[0]) < 1e-12:
                return 0.0
            return (wl - coeffs[1]) / coeffs[0]
        poly_rev = coeffs.copy()
        poly_rev[-1] -= wl
        roots = np.roots(poly_rev)
        real_roots = roots[np.isreal(roots)].real
        valid = real_roots[(real_roots >= 0) & (real_roots < n_pixels)]
        if len(valid) > 0:
            return float(valid[0])
        pixels = np.arange(n_pixels)
        wls = np.polyval(coeffs, pixels)
        idx = np.argmin(np.abs(wls - wl))
        return float(idx)

    def update_spectrum():
        """Update the spectrum plot and optional calibration overlay from the current line ROI.

        Inputs:
            None (uses `frame`, `line_start`, `line_end`, `thickness`, `pairs`, `fit_type`, and `show_wavelength_x`).
        Output:
            None (side-effect updates spectrum line and calibration markers on `ax_spec`).
        Transformation:
            Extracts line profile intensities from the image, maps x-axis to either Pixel or wavelength,
            and updates marker positions to match the current calibration pairs.
        """
        start = (int(line_start[0]), int(line_start[1]))
        end = (int(line_end[0]), int(line_end[1]))
        intensities = extract_line_profile(frame, start, end, thickness)
        pixels = np.arange(len(intensities))
        coeffs = _coeffs_for_current_pairs()
        if show_wavelength_x and coeffs is not None:
            x_data = np.polyval(coeffs, pixels)
            ax_spec.set_xlabel("λ (nm)")
        else:
            x_data = pixels
            ax_spec.set_xlabel("Pixel")
        spec_line.set_data(x_data, intensities)
        ax_spec.relim()
        ax_spec.autoscale_view()
        if pairs:
            px = [p[0] for p in pairs]
            if show_wavelength_x and coeffs is not None:
                cal_x = np.polyval(coeffs, px)
            else:
                cal_x = px
            py = []
            for pi in px:
                idx = int(round(pi))
                if 0 <= idx < len(intensities):
                    py.append(intensities[idx])
                else:
                    py.append(0)
            cal_markers.set_data(cal_x, py)
        else:
            cal_markers.set_data([], [])

    def _compute_r2(coeffs):
        """Compute R² for how well the given coefficients fit the current calibration pairs.

        Inputs:
            coeffs: Calibration coefficients.
        Output:
            R² as float, or None if not computable (e.g. fewer than 2 pairs or zero variance).
        Transformation:
            Computes predicted wavelengths for the given pixel positions and uses `1 - SS_res/SS_tot`.
        """
        if len(pairs) < 2:
            return None
        pixels = np.array([p[0] for p in pairs])
        wavelengths = np.array([p[1] for p in pairs])
        pred = np.polyval(coeffs, pixels)
        ss_res = np.sum((wavelengths - pred) ** 2)
        ss_tot = np.sum((wavelengths - np.mean(wavelengths)) ** 2)
        return 1 - ss_res / ss_tot if ss_tot > 0 else None

    def update_list_display():
        """Render calibration pairs text into the calibration list panel.

        Inputs:
            None (uses `pairs`, `ax_list`).
        Output:
            None (side-effect clears and redraws `ax_list`).
        Transformation:
            Clears existing text, shows `(none)` when empty, otherwise renders ordered entries `px -> nm`.
        """
        fit_text_artist[0] = None
        ax_list.clear()
        ax_list.set_axis_off()
        ax_list.set_title(f"Calibration points — {channel['id']}")
        if not pairs:
            ax_list.text(0.02, 0.9, "(none)", transform=ax_list.transAxes, fontsize=9)
        else:
            for i, (px, wl) in enumerate(pairs):
                y = 0.98 - i * LIST_LINE_STEP
                ax_list.text(0.02, y, f"{i+1}. {px:.1f} px → {wl:.1f} nm", transform=ax_list.transAxes, fontsize=9)

    fit_text_artist = [None]

    def update_fit_display():
        """Render the current fit equation and R² value for the calibration pairs.

        Inputs:
            None (uses `pairs`, `fit_type`, `poly_degree`, `ax_list` and `fit_text_artist`).
        Output:
            None (side-effect creates/removes a matplotlib text artist).
        Transformation:
            Computes calibration coefficients via `fit_calibration`, formats the equation string,
            computes R² using `_compute_r2`, and updates the panel.
        """
        if fit_text_artist[0] is not None:
            fit_text_artist[0].remove()
            fit_text_artist[0] = None
        if len(pairs) < 2:
            fit_text_artist[0] = ax_list.text(0.55, 0.5, "Fit: —", transform=ax_list.transAxes, fontsize=9)
        else:
            coeffs = fit_calibration([tuple(p) for p in pairs], fit_type, poly_degree)
            r2 = _compute_r2(coeffs)
            if fit_type == "linear":
                coef_str = f"λ = {coeffs[0]:.4f}·px + {coeffs[1]:.4f}"
            else:
                parts = []
                for i, c in enumerate(coeffs):
                    exp = len(coeffs) - 1 - i
                    if exp == 0:
                        parts.append(f"{c:.4f}")
                    elif exp == 1:
                        parts.append(f"{c:.4f}·px")
                    else:
                        parts.append(f"{c:.4f}·px^{exp}")
                coef_str = "λ = " + " + ".join(parts)
            r2_str = f"R² = {r2:.6f}" if r2 is not None else "R² = —"
            fit_text_artist[0] = ax_list.text(0.55, 0.5, f"Fit: {fit_type}\n{coef_str}\n{r2_str}", transform=ax_list.transAxes, fontsize=8)

    def _cancel_spectrum_timer():
        t = spectrum_timer_ref[0]
        if t is not None:
            try:
                t.stop()
            except Exception:
                pass
            spectrum_timer_ref[0] = None

    def _schedule_spectrum_update():
        _cancel_spectrum_timer()

        def _fire():
            spectrum_timer_ref[0] = None
            update_spectrum()
            fig.canvas.draw_idle()

        timer = fig.canvas.new_timer(interval=SPECTRUM_DEBOUNCE_MS)
        timer.single_shot = True
        timer.add_callback(_fire)
        timer.start()
        spectrum_timer_ref[0] = timer

    def on_slider_change(_):
        """Handle ROI slider changes: line updates immediately; spectrum after debounce."""
        if suppress_slider_callback[0]:
            return
        line_start[0] = int(slider_start_x.val)
        line_start[1] = int(slider_start_y.val)
        line_end[0] = int(slider_end_x.val)
        line_end[1] = int(slider_end_y.val)
        update_line_display()
        _schedule_spectrum_update()
        fig.canvas.draw_idle()

    def refresh():
        """Refresh line, spectrum, list, and fit; cancel pending spectrum debounce; one canvas draw."""
        _cancel_spectrum_timer()
        update_line_display()
        update_spectrum()
        update_list_display()
        update_fit_display()
        fig.canvas.draw_idle()

    def on_image_click(event):
        """Handle clicks on the preview image to set the line endpoints.

        Inputs:
            event: Matplotlib mouse event containing `inaxes`, `xdata`, `ydata`.
        Output:
            None (side-effect updates `line_start`/`line_end`, sliders, and redraws).
        Transformation:
            - Converts click coordinates to integer pixel positions (clamped to image bounds).
            - Alternates between selecting start and end endpoints.
            - Synchronizes sliders and refreshes the UI.
        """
        if event.inaxes != ax_img or event.xdata is None:
            return
        nonlocal line_click_count
        x = int(round(event.xdata))
        y = int(round(event.ydata))
        x = max(0, min(w - 1, x))
        y = max(0, min(h - 1, y))
        if line_click_count == 0:
            line_start[0], line_start[1] = x, y
            line_click_count = 1
            ax_img.set_title("Click end point of line")
        else:
            line_end[0], line_end[1] = x, y
            line_click_count = 0
            ax_img.set_title("Camera image — click two points to set line")
        _sync_sliders_to_line()
        refresh()

    def set_line_click(_):
        """Switch UI mode to “define line” and reset any in-progress calibration edits.

        Inputs:
            _: unused callback payload.
        Output:
            None (side-effect resets click-mode state and updates panel titles/boxes).
        Transformation:
            Resets `line_click_count`, disables calibration-add mode, clears pending pixel/index state,
            resets UI text input boxes, and refreshes the display.
        """
        nonlocal line_click_count, add_calibration_mode, pending_pixel, editing_index
        line_click_count = 0
        add_calibration_mode = False
        pending_pixel = None
        editing_index = None
        ax_img.set_title("Camera image — click two points to set line")
        ax_spec.set_title("Spectrum (intensity vs pixel) — click to add calibration point")
        status_label.set_text("")
        pixel_box.set_val("")
        wl_box.set_val("")
        refresh()

    def add_calibration_click(_):
        """Enable calibration-point mode for the spectrum panel.

        Inputs:
            _: unused callback payload.
        Output:
            None (side-effect updates state variables and prompts user via UI text).
        Transformation:
            Sets `add_calibration_mode=True`, clears editing state, resets input boxes,
            and updates axis titles to instruct the next user action.
        """
        nonlocal add_calibration_mode, editing_index
        add_calibration_mode = True
        editing_index = None
        pixel_box.set_val("")
        wl_box.set_val("")
        ax_spec.set_title("Spectrum — click a point, then enter wavelength in box below")
        fig.canvas.draw_idle()

    def _snap_to_local_max(clicked_pixel: float, half_window: int = 25) -> float:
        """Snap a clicked pixel coordinate to the nearest local maximum.

        Inputs:
            clicked_pixel: Pixel position chosen by the user (float).
            half_window: Search radius in points around the rounded pixel index.
        Output:
            Pixel index (float) corresponding to the local maximum within the window.
        Transformation:
            Reads the current intensity curve (`spec_line` y-data), searches `argmax` in a bounded window,
            and returns the index of that maximum.
        """
        intensities = spec_line.get_ydata()
        if len(intensities) == 0:
            return clicked_pixel
        idx = int(round(clicked_pixel))
        lo = max(0, idx - half_window)
        hi = min(len(intensities) - 1, idx + half_window)
        window = intensities[lo : hi + 1]
        local_max_offset = np.argmax(window)
        return float(lo + local_max_offset)

    def on_spectrum_click_handler(event):
        """Handle clicks on the spectrum plot to select/edit a calibration pixel.

        Inputs:
            event: Matplotlib mouse event with `.inaxes` and `.xdata`.
        Output:
            None (side-effect updates pending pixel selection and UI fields).
        Transformation:
            - Active in add-calibration mode or while editing a point (`editing_index` set).
            - Converts x coordinate to pixel space (optionally inverts wavelength->pixel using calibration coefficients).
            - Snaps the pixel to a nearby local maximum to improve calibration stability.
            - In edit mode: updates the pair’s pixel, re-sorts, fixes `editing_index`, syncs boxes, refreshes plot.
        """
        nonlocal pending_pixel, editing_index, _skip_wl_submit
        if event.inaxes != ax_spec or event.xdata is None:
            return
        if not add_calibration_mode and editing_index is None:
            return
        clicked = float(event.xdata)
        coeffs = _coeffs_for_current_pairs()
        if show_wavelength_x and coeffs is not None:
            intensities = spec_line.get_ydata()
            n_px = len(intensities)
            clicked = _wavelength_to_pixel(clicked, coeffs, n_px)
        snapped = _snap_to_local_max(clicked, half_window=5)

        if editing_index is not None:
            wl_keep = float(pairs[editing_index][1])
            pairs[editing_index] = [snapped, wl_keep]
            pairs.sort(key=lambda p: p[0])
            editing_index = min(
                range(len(pairs)),
                key=lambda i: abs(pairs[i][0] - snapped) + 1e3 * abs(pairs[i][1] - wl_keep),
            )
            _skip_wl_submit = True
            try:
                pixel_box.set_val(f"{pairs[editing_index][0]:.1f}")
                wl_box.set_val(f"{pairs[editing_index][1]:.1f}")
                pt_box.set_val(str(editing_index + 1))
            finally:
                _skip_wl_submit = False
            if abs(snapped - clicked) > 0.5:
                status_label.set_text(
                    f"Edit: pixel → {pairs[editing_index][0]:.1f} (snapped) — click again or Update / Enter"
                )
            else:
                status_label.set_text(
                    f"Edit point {editing_index + 1}: pixel {pairs[editing_index][0]:.1f} — Update or Enter on λ"
                )
            refresh()
            return

        pending_pixel = snapped
        pixel_box.set_val(f"{snapped:.1f}")
        wl_box.set_val("")
        if abs(snapped - clicked) > 0.5:
            status_label.set_text(f"Pixel {snapped:.1f} (snapped from {clicked:.1f}) — enter wavelength (nm) below")
        else:
            status_label.set_text(f"Pixel {pending_pixel:.1f} — enter wavelength (nm) below, press Enter")
        fig.canvas.draw_idle()

    def on_wavelength_submit(text):
        """Accept wavelength entry (user presses Enter) and update calibration pairs.

        Inputs:
            text: User-entered wavelength string.
        Output:
            None (side-effect updates `pairs`, clears boxes, refreshes UI, and updates status).
        Transformation:
            Parses wavelength, reads pixel from `pixel_box`, validates range,
            then either edits an existing pair (`editing_index`) or appends a new pair (`pending_pixel`).
            Finally sorts pairs and calls `refresh()`.
        """
        nonlocal pending_pixel, editing_index, _skip_wl_submit
        if _skip_wl_submit:
            return
        try:
            wl = float(text.strip())
            px_str = pixel_box.text.strip()
            if not px_str:
                return
            px = float(px_str)
            if not (WL_MIN_NM <= wl <= WL_MAX_NM):
                return
            if editing_index is not None:
                pairs[editing_index] = [px, wl]
                pairs.sort(key=lambda p: p[0])
                editing_index = None
                status_label.set_text("Point updated")
            elif pending_pixel is not None:
                pairs.append([px, wl])
                pairs.sort(key=lambda p: p[0])
                pending_pixel = None
                status_label.set_text("")
            pixel_box.set_val("")
            wl_box.set_val("")
            refresh()
        except ValueError:
            pass

    def fit_linear_click(_):
        """Switch the calibration fit model to linear (λ = a*px + b)."""
        nonlocal fit_type
        fit_type = "linear"
        fit_label.set_text(f"Fit: {fit_type}")
        refresh()

    def fit_poly_click(_):
        """Switch the calibration fit model to polynomial (λ = poly(px))."""
        nonlocal fit_type
        fit_type = "polynomial"
        fit_label.set_text(f"Fit: {fit_type}")
        refresh()

    def _get_selected_index():
        """Resolve the currently selected point index from the UI text box.

        Inputs:
            None (reads `pt_box.text`).
        Output:
            Selected pair index as integer (0-based), or None if invalid/out of range.
        Transformation:
            Parses `pt_box.text` as 1-based UI index and converts to 0-based internal index.
        """
        try:
            i = int(pt_box.text.strip())
            if 1 <= i <= len(pairs):
                return i - 1
        except ValueError:
            pass
        return None

    def delete_click(_):
        """Delete the calibration pair selected in the UI (by point number)."""
        idx = _get_selected_index()
        if idx is not None:
            pairs.pop(idx)
            status_label.set_text("Point deleted")
            refresh()
        else:
            status_label.set_text("Select valid point #")

    def edit_click(_):
        """Enter edit mode for the selected calibration pair.

        Inputs:
            _: unused callback payload.
        Output:
            None (side-effect populates input boxes and sets edit state flags).
        Transformation:
            - Determines selected index from `pt_box`.
            - Loads pixel/wavelength values into `pixel_box`/`wl_box`.
            - Sets `editing_index` and disables add-calibration mode so the next Enter updates the same pair.
        """
        nonlocal editing_index, pending_pixel, add_calibration_mode, _skip_wl_submit
        idx = _get_selected_index()
        if idx is not None:
            editing_index = idx
            pending_pixel = None
            add_calibration_mode = False
            px, wl = pairs[idx]
            _skip_wl_submit = True
            try:
                pixel_box.set_val(f"{px:.1f}")
                wl_box.set_val(f"{wl:.1f}")
            finally:
                _skip_wl_submit = False
            status_label.set_text(
                f"Editing point {idx+1} — change px/λ in boxes, click spectrum to move pixel, then Update or Enter"
            )
            ax_spec.set_title("Spectrum — click to move pixel for edited point")
        else:
            status_label.set_text("Select valid point #")
        fig.canvas.draw_idle()

    def update_click(_):
        """Apply updated pixel/wavelength values to the currently edited calibration pair."""
        nonlocal editing_index
        if editing_index is None:
            return
        try:
            wl = float(wl_box.text.strip())
            px_str = pixel_box.text.strip()
            if not px_str:
                return
            px = float(px_str)
            if not (WL_MIN_NM <= wl <= WL_MAX_NM):
                return
            pairs[editing_index] = [px, wl]
            pairs.sort(key=lambda p: p[0])
            editing_index = None
            status_label.set_text("Point updated")
            pixel_box.set_val("")
            wl_box.set_val("")
            refresh()
        except ValueError:
            pass

    ax_lamp = plt.axes([0.02, 0.135, 0.62, 0.07])
    ax_auto_cal = plt.axes([0.65, 0.135, 0.12, 0.07])
    ax_set_line = plt.axes([0.02, 0.02, 0.06, 0.10])
    ax_add_cal = plt.axes([0.09, 0.02, 0.09, 0.10])
    ax_fit_linear = plt.axes([0.19, 0.02, 0.05, 0.10])
    ax_fit_poly = plt.axes([0.25, 0.02, 0.07, 0.10])
    ax_save = plt.axes([0.33, 0.02, 0.07, 0.10])
    ax_thick = plt.axes([0.41, 0.02, 0.08, 0.10])
    ax_pixel = plt.axes([0.50, 0.02, 0.08, 0.10])
    ax_wl = plt.axes([0.59, 0.02, 0.12, 0.10])
    ax_pt = plt.axes([0.72, 0.02, 0.04, 0.10])
    ax_del = plt.axes([0.77, 0.02, 0.04, 0.10])
    ax_edit = plt.axes([0.82, 0.02, 0.04, 0.10])
    ax_update = plt.axes([0.87, 0.02, 0.05, 0.10])
    ax_wl_x = plt.axes([0.93, 0.02, 0.05, 0.10])

    lamp_names = list(LAMP_LIBRARY.keys())
    default_lamp_name = "Neon" if "Neon" in LAMP_LIBRARY else (lamp_names[0] if lamp_names else "")
    selected_lamp = [default_lamp_name]
    lamp_radio = widgets.RadioButtons(ax_lamp, lamp_names, active=lamp_names.index(default_lamp_name))
    lamp_radio.on_clicked(lambda label: selected_lamp.__setitem__(0, label))
    btn_auto_cal = widgets.Button(ax_auto_cal, "Auto cal")

    btn_set_line = widgets.Button(ax_set_line, "Set line")
    btn_add_cal = widgets.Button(ax_add_cal, "Add calibration point")
    btn_fit_linear = widgets.Button(ax_fit_linear, "Linear")
    btn_fit_poly = widgets.Button(ax_fit_poly, "Polynomial")
    btn_save = widgets.Button(ax_save, "Save config")
    thick_box = widgets.TextBox(ax_thick, "Thick ", initial=str(thickness))
    pixel_box = widgets.TextBox(ax_pixel, "px ", initial="")
    wl_box = widgets.TextBox(ax_wl, "λ (nm) ", initial="")
    pt_box = widgets.TextBox(ax_pt, "Pt ", initial="1")
    btn_del = widgets.Button(ax_del, "Del")
    btn_edit = widgets.Button(ax_edit, "Edit")
    btn_update = widgets.Button(ax_update, "Update")
    check_wl_x = widgets.CheckButtons(ax_wl_x, ["λ on x"], [show_wavelength_x])

    status_label = ax_btns.text(0.02, 0.5, "", transform=ax_btns.transAxes, fontsize=9)
    fit_label = ax_btns.text(0.85, 0.5, f"Fit: {fit_type}", transform=ax_btns.transAxes, fontsize=10)

    def _resolve_calibration_for_channel(ch: dict) -> dict:
        calib_id = ch.get("calibration_id") or "default"
        c = next((x for x in calibrations if x["id"] == calib_id), None)
        if c is None:
            c = {"id": calib_id, "pairs": [], "fit": "polynomial", "polynomial_degree": 2}
            calibrations.append(c)
            ch["calibration_id"] = calib_id
        return c

    def _load_cfg_to_ui():
        nonlocal thickness, fit_type, poly_degree
        line_start[0] = int(channel["line"]["start"][0])
        line_start[1] = int(channel["line"]["start"][1])
        line_end[0] = int(channel["line"]["end"][0])
        line_end[1] = int(channel["line"]["end"][1])
        thickness = int(channel["line"].get("thickness", 5))
        pairs.clear()
        pairs.extend([list(p) for p in cal.get("pairs", [])])
        fit_type = cal.get("fit", "polynomial")
        poly_degree = int(cal.get("polynomial_degree", 2))
        _sync_sliders_to_line()
        thick_box.set_val(str(thickness))
        channel_id_box.set_val(channel["id"])
        fit_label.set_text(f"Fit: {fit_type}")
        pt_box.set_val("1")

    def channel_apply_click(_):
        nonlocal channel, cal, line_click_count, add_calibration_mode, pending_pixel, editing_index
        _flush_current_to_cfg()
        raw = _normalize_channel_id(channel_id_box.text)
        ch = _find_channel_by_id(channels, raw)
        if ch is None:
            calib_id = f"cal_{raw}"
            ch = {
                "id": raw,
                "line": {
                    "start": [0, 0],
                    "end": [w - 1, h // 2],
                    "thickness": 5,
                },
                "calibration_id": calib_id,
            }
            channels.append(ch)
            if not any(x["id"] == calib_id for x in calibrations):
                calibrations.append(
                    {"id": calib_id, "pairs": [], "fit": "polynomial", "polynomial_degree": 2}
                )
        channel = ch
        cal = _resolve_calibration_for_channel(channel)
        _load_cfg_to_ui()
        line_click_count = 0
        add_calibration_mode = False
        pending_pixel = None
        editing_index = None
        ax_img.set_title("Camera image — click two points to set line")
        ax_spec.set_title("Spectrum (intensity vs pixel) — click to add calibration point")
        pixel_box.set_val("")
        wl_box.set_val("")
        status_label.set_text(f"Channel: {channel['id']}")
        refresh()

    def channel_new_click(_):
        nonlocal channel, cal, line_click_count, add_calibration_mode, pending_pixel, editing_index
        _flush_current_to_cfg()
        existing = {_normalize_channel_id(c.get("id", "")) for c in channels}
        n = 0
        while f"ch{n}" in existing:
            n += 1
        cid = f"ch{n}"
        calib_id = f"cal_{cid}"
        ch = {
            "id": cid,
            "line": {"start": [0, 0], "end": [w - 1, h // 2], "thickness": 5},
            "calibration_id": calib_id,
        }
        channels.append(ch)
        calibrations.append(
            {"id": calib_id, "pairs": [], "fit": "polynomial", "polynomial_degree": 2}
        )
        channel = ch
        cal = next(c for c in calibrations if c["id"] == calib_id)
        _load_cfg_to_ui()
        line_click_count = 0
        add_calibration_mode = False
        pending_pixel = None
        editing_index = None
        ax_img.set_title("Camera image — click two points to set line")
        ax_spec.set_title("Spectrum (intensity vs pixel) — click to add calibration point")
        pixel_box.set_val("")
        wl_box.set_val("")
        status_label.set_text(f"New channel: {cid}")
        refresh()

    def save_click(_):
        """Persist full config: flush active channel UI state, then write JSON."""
        _flush_current_to_cfg()
        try:
            save_spectrometer_config(cfg, config_path)
            status_label.set_text(f"Saved {len(channels)} channel(s) to {config_path}")
        except Exception as e:
            status_label.set_text(f"Error: {e}")
        fig.canvas.draw_idle()

    def auto_cal_click(_):
        """Detect peaks, assign reference wavelengths (either dispersion direction), replace pairs."""
        nonlocal pending_pixel, editing_index, add_calibration_mode
        refs = LAMP_LIBRARY[selected_lamp[0]]
        start = (int(line_start[0]), int(line_start[1]))
        end = (int(line_end[0]), int(line_end[1]))
        intensities = extract_line_profile(frame, start, end, thickness)
        new_pairs, msg = auto_calibration_pairs(intensities, refs, fit_type, poly_degree)
        if not new_pairs:
            status_label.set_text(msg)
            fig.canvas.draw_idle()
            return
        pairs.clear()
        pairs.extend(new_pairs)
        pending_pixel = None
        editing_index = None
        add_calibration_mode = False
        status_label.set_text(msg)
        refresh()

    def on_thickness_submit(text):
        """Handle line thickness input submission from the text box.

        Inputs:
            text: User-entered thickness value (string).
        Output:
            None (side-effect updates `thickness` and refreshes the spectrum UI).
        Transformation:
            Parses `text` as integer, clamps to allowed range (1..31), assigns to `thickness`, then calls `refresh()`.
        """
        nonlocal thickness
        try:
            t = int(text.strip())
            if 1 <= t <= 31:
                thickness = t
                refresh()
        except ValueError:
            pass

    def on_wl_x_toggle(label):
        """Toggle whether the spectrum x-axis is wavelength or pixel index.

        Inputs:
            label: Clicked status label from matplotlib CheckButtons.
        Output:
            None (side-effect updates `show_wavelength_x` and refreshes UI).
        Transformation:
            Reads checkbox state (`check_wl_x.get_status()`), updates `show_wavelength_x`, and calls `refresh()`.
        """
        nonlocal show_wavelength_x
        show_wavelength_x = check_wl_x.get_status()[0]
        refresh()

    slider_start_x.on_changed(on_slider_change)
    slider_start_y.on_changed(on_slider_change)
    slider_end_x.on_changed(on_slider_change)
    slider_end_y.on_changed(on_slider_change)
    check_wl_x.on_clicked(on_wl_x_toggle)

    thick_box.on_submit(on_thickness_submit)
    wl_box.on_submit(on_wavelength_submit)

    def on_channel_id_submit(_text):
        channel_apply_click(None)

    channel_id_box.on_submit(on_channel_id_submit)

    def on_click(event):
        """Global click handler that dispatches clicks to the correct axis-specific callbacks.

        Inputs:
            event: Matplotlib mouse event.
        Output:
            None (calls `on_image_click` or `on_spectrum_click_handler` depending on the clicked axes).
        Transformation:
            Routes based on `event.inaxes` and the axis objects (`ax_img`, `ax_spec`).
        """
        if event.inaxes == ax_img:
            on_image_click(event)
        elif event.inaxes == ax_spec:
            on_spectrum_click_handler(event)

    btn_set_line.on_clicked(set_line_click)
    btn_add_cal.on_clicked(add_calibration_click)
    btn_ch_apply.on_clicked(channel_apply_click)
    btn_ch_new.on_clicked(channel_new_click)
    btn_auto_cal.on_clicked(auto_cal_click)
    btn_fit_linear.on_clicked(fit_linear_click)
    btn_fit_poly.on_clicked(fit_poly_click)
    btn_save.on_clicked(save_click)
    btn_del.on_clicked(delete_click)
    btn_edit.on_clicked(edit_click)
    btn_update.on_clicked(update_click)

    tooltip_annot = ax_btns.annotate(
        "", xy=(0, 0), xycoords="figure pixels",
        textcoords="offset points", xytext=(10, 25),
        fontsize=8, bbox=dict(boxstyle="round,pad=0.3", fc="w", alpha=0.95),
    )
    tooltip_annot.set_visible(False)
    tooltip_annot.set_picker(False)
    tooltip_axes = {
        ax_img: "Click two points to set the spectrum line",
        ax_spec: "Spectrum — click to add calibration point when in Add mode",
        ax_start_y: "Fine-tune start marker Y (above X)",
        ax_start_x: "Fine-tune start marker X",
        ax_end_y: "Fine-tune end marker Y (above X)",
        ax_end_x: "Fine-tune end marker X",
        ax_channel_id: "Channel id (e.g. ch0). Go loads or creates it.",
        ax_ch_apply: "Load channel id from box; creates new channel + cal if unknown id.",
        ax_ch_new: "Add ch0, ch1, … with empty calibration; previous channel kept in memory.",
        ax_set_line: "Click two points on the image to define the spectrum line",
        ax_add_cal: "Click spectrum to add a calibration point. Enter wavelength in λ box.",
        ax_fit_linear: "Use linear fit for pixel → wavelength",
        ax_fit_poly: "Use polynomial fit for pixel → wavelength",
        ax_save: "Save calibration config to file",
        ax_thick: "Line thickness (pixels) for spectrum extraction",
        ax_pixel: "Pixel index (auto-filled on click, or type manually)",
        ax_wl: "Wavelength in nm. Press Enter to add or update.",
        ax_pt: "Point index (1-based) for Edit/Delete",
        ax_del: "Delete the point selected in Pt",
        ax_edit: "Load selected point into px/λ for editing.",
        ax_update: "Apply edited values (after Edit). Does not add new points.",
        ax_wl_x: "Show wavelength (nm) on spectrum x-axis instead of pixel index.",
        ax_lamp: "Calibration lamp selection (hardcoded reference wavelengths).",
        ax_auto_cal: "Find peaks and assign wavelengths; tries both dispersion directions (lower RSS wins).",
    }

    def on_hover(event):
        """Global hover handler to show tooltips when the mouse is over known UI elements.

        Inputs:
            event: Matplotlib motion event.
        Output:
            None (side-effect updates tooltip annotation visibility/text).
        Transformation:
            If `event.inaxes` is in `tooltip_axes`, updates tooltip text and makes it visible;
            otherwise hides the tooltip.
        """
        ax = event.inaxes
        if ax in tooltip_axes:
            text = tooltip_axes[ax]
            vis = True
        else:
            text = ""
            vis = False
        axes_changed = ax != tooltip_state["axes"]
        vis_changed = vis != tooltip_state["visible"]
        text_changed = vis and text != tooltip_state["text"]
        tooltip_state["axes"] = ax
        tooltip_state["visible"] = vis
        tooltip_state["text"] = text if vis else ""

        if vis:
            tooltip_annot.set_text(text)
            tooltip_annot.xy = (event.x, event.y)
            tooltip_annot.set_visible(True)
        else:
            tooltip_annot.set_visible(False)

        if axes_changed or vis_changed or text_changed:
            fig.canvas.draw_idle()

    fig.canvas.mpl_connect("button_press_event", on_click)
    fig.canvas.mpl_connect("motion_notify_event", on_hover)

    refresh()
    plt.show()


if __name__ == "__main__":
    main()
