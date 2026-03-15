#!/usr/bin/env python3
"""
Spectrometer calibration wizard. Interactive UI for line selection and wavelength calibration.
Runs on a device with display (not the headless sensor). Load preview image, define line,
click spectrum to add calibration pairs, save config.
"""
import argparse
import os
import sys

import cv2
import matplotlib.pyplot as plt
import matplotlib.widgets as widgets
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.config import load_spectrometer_config, save_spectrometer_config
from lib.spectrum import extract_line_profile, fit_calibration


def _default_image_path():
    candidates = [
        "spectrometer_preview.png",
        "/tmp/spectrometer_preview.png",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return candidates[0]


def _default_config_path():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(script_dir), "spectrometer_config.json")


def main():
    ap = argparse.ArgumentParser(description="Spectrometer calibration wizard (GUI)")
    ap.add_argument("--image", default=None, help="Preview image path")
    ap.add_argument("--config", default=None, help="Output config path")
    ap.add_argument("--channel-id", default="ch0", help="Channel ID")
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

    channel = next((c for c in channels if c["id"] == args.channel_id), None)
    if channel is None:
        channel = {
            "id": args.channel_id,
            "line": {"start": [0, 0], "end": [frame.shape[1] - 1, frame.shape[0] // 2], "thickness": 5},
            "calibration_id": "default",
        }
        channels.append(channel)

    cal = next((c for c in calibrations if c["id"] == channel["calibration_id"]), None)
    if cal is None:
        cal = {"id": channel["calibration_id"], "pairs": [], "fit": "polynomial", "polynomial_degree": 2}
        calibrations.append(cal)

    line_start = list(channel["line"]["start"])
    line_end = list(channel["line"]["end"])
    thickness = channel["line"].get("thickness", 5)
    pairs = [list(p) for p in cal["pairs"]]
    fit_type = cal.get("fit", "polynomial")
    poly_degree = cal.get("polynomial_degree", 2)

    line_click_count = 0
    add_calibration_mode = False
    pending_pixel = None
    editing_index = None
    _skip_wl_submit = False
    show_wavelength_x = False

    h, w = frame.shape
    fig = plt.figure(figsize=(14, 10))
    gs = fig.add_gridspec(
        5, 1,
        height_ratios=[2.2, 0.5, 1.5, 1, 0.9],
        left=0.02, right=0.98, top=0.96, bottom=0.18,
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

    ax_start_x = plt.axes([0.02, 0.62, 0.20, 0.03])
    ax_start_y = plt.axes([0.24, 0.62, 0.20, 0.03])
    ax_end_x = plt.axes([0.46, 0.62, 0.20, 0.03])
    ax_end_y = plt.axes([0.68, 0.62, 0.20, 0.03])

    slider_start_x = widgets.Slider(ax_start_x, "Start X", 0, w - 1, valinit=line_start[0], valstep=1)
    slider_start_y = widgets.Slider(ax_start_y, "Start Y", 0, h - 1, valinit=line_start[1], valstep=1)
    slider_end_x = widgets.Slider(ax_end_x, "End X", 0, w - 1, valinit=line_end[0], valstep=1)
    slider_end_y = widgets.Slider(ax_end_y, "End Y", 0, h - 1, valinit=line_end[1], valstep=1)

    img_display = ax_img.imshow(frame, cmap="gray", aspect="auto")
    line_artist, = ax_img.plot([], [], "r-", linewidth=1)
    start_marker, = ax_img.plot([], [], "go", markersize=3)
    end_marker, = ax_img.plot([], [], "ro", markersize=3)

    ax_spec.set_aspect("auto")
    spec_line, = ax_spec.plot([], [], "b-", linewidth=1)
    cal_markers, = ax_spec.plot([], [], "r|", markersize=12)

    def _sync_sliders_to_line():
        slider_start_x.set_val(line_start[0])
        slider_start_y.set_val(line_start[1])
        slider_end_x.set_val(line_end[0])
        slider_end_y.set_val(line_end[1])

    def update_line_display():
        line_artist.set_data([line_start[0], line_end[0]], [line_start[1], line_end[1]])
        start_marker.set_data([line_start[0]], [line_start[1]])
        end_marker.set_data([line_end[0]], [line_end[1]])
        fig.canvas.draw_idle()

    def _wavelength_to_pixel(wl: float, coeffs: np.ndarray, n_pixels: int) -> float:
        """Convert wavelength to pixel index using calibration coefficients."""
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
        start = (int(line_start[0]), int(line_start[1]))
        end = (int(line_end[0]), int(line_end[1]))
        intensities = extract_line_profile(frame, start, end, thickness)
        pixels = np.arange(len(intensities))
        if show_wavelength_x and len(pairs) >= 2:
            coeffs = fit_calibration([tuple(p) for p in pairs], fit_type, poly_degree)
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
            if show_wavelength_x and len(pairs) >= 2:
                coeffs = fit_calibration([tuple(p) for p in pairs], fit_type, poly_degree)
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
        fig.canvas.draw_idle()

    def _compute_r2(coeffs):
        if len(pairs) < 2:
            return None
        pixels = np.array([p[0] for p in pairs])
        wavelengths = np.array([p[1] for p in pairs])
        pred = np.polyval(coeffs, pixels)
        ss_res = np.sum((wavelengths - pred) ** 2)
        ss_tot = np.sum((wavelengths - np.mean(wavelengths)) ** 2)
        return 1 - ss_res / ss_tot if ss_tot > 0 else None

    def update_list_display():
        ax_list.clear()
        ax_list.set_axis_off()
        ax_list.set_title("Calibration points")
        if not pairs:
            ax_list.text(0.02, 0.9, "(none)", transform=ax_list.transAxes, fontsize=9)
        else:
            for i, (px, wl) in enumerate(pairs):
                y = 0.98 - i * 0.06
                ax_list.text(0.02, y, f"{i+1}. {px:.1f} px → {wl:.1f} nm", transform=ax_list.transAxes, fontsize=9)
        fig.canvas.draw_idle()

    fit_text_artist = [None]

    def update_fit_display():
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
        fig.canvas.draw_idle()

    def on_slider_change(_):
        line_start[0] = int(slider_start_x.val)
        line_start[1] = int(slider_start_y.val)
        line_end[0] = int(slider_end_x.val)
        line_end[1] = int(slider_end_y.val)
        refresh()

    def refresh():
        update_line_display()
        update_spectrum()
        update_list_display()
        update_fit_display()

    def on_image_click(event):
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
        nonlocal add_calibration_mode, editing_index
        add_calibration_mode = True
        editing_index = None
        pixel_box.set_val("")
        wl_box.set_val("")
        ax_spec.set_title("Spectrum — click a point, then enter wavelength in box below")
        fig.canvas.draw_idle()

    def _snap_to_local_max(clicked_pixel: float, half_window: int = 25) -> float:
        """Snap clicked pixel to local maximum within ±half_window points."""
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
        nonlocal pending_pixel
        if event.inaxes != ax_spec or event.xdata is None:
            return
        if not add_calibration_mode:
            return
        clicked = float(event.xdata)
        if show_wavelength_x and len(pairs) >= 2:
            coeffs = fit_calibration([tuple(p) for p in pairs], fit_type, poly_degree)
            intensities = spec_line.get_ydata()
            n_px = len(intensities)
            clicked = _wavelength_to_pixel(clicked, coeffs, n_px)
        snapped = _snap_to_local_max(clicked, half_window=5)
        pending_pixel = snapped
        pixel_box.set_val(f"{snapped:.1f}")
        wl_box.set_val("")
        if abs(snapped - clicked) > 0.5:
            status_label.set_text(f"Pixel {snapped:.1f} (snapped from {clicked:.1f}) — enter wavelength (nm) below")
        else:
            status_label.set_text(f"Pixel {pending_pixel:.1f} — enter wavelength (nm) below, press Enter")
        fig.canvas.draw_idle()

    def on_wavelength_submit(text):
        nonlocal pending_pixel, editing_index, _skip_wl_submit
        if _skip_wl_submit:
            return
        try:
            wl = float(text.strip())
            px_str = pixel_box.text.strip()
            if not px_str:
                return
            px = float(px_str)
            if not (200 <= wl <= 1200):
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
        nonlocal fit_type
        fit_type = "linear"
        fit_label.set_text(f"Fit: {fit_type}")
        update_fit_display()

    def fit_poly_click(_):
        nonlocal fit_type
        fit_type = "polynomial"
        fit_label.set_text(f"Fit: {fit_type}")
        update_fit_display()

    def _get_selected_index():
        try:
            i = int(pt_box.text.strip())
            if 1 <= i <= len(pairs):
                return i - 1
        except ValueError:
            pass
        return None

    def delete_click(_):
        idx = _get_selected_index()
        if idx is not None:
            pairs.pop(idx)
            status_label.set_text("Point deleted")
            refresh()
        else:
            status_label.set_text("Select valid point #")

    def edit_click(_):
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
            status_label.set_text(f"Editing point {idx+1} — change values, press Enter or Update")
        else:
            status_label.set_text("Select valid point #")
        fig.canvas.draw_idle()

    def update_click(_):
        nonlocal editing_index
        if editing_index is None:
            return
        try:
            wl = float(wl_box.text.strip())
            px_str = pixel_box.text.strip()
            if not px_str:
                return
            px = float(px_str)
            if not (200 <= wl <= 1200):
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

    def save_click(_):
        channel["line"] = {
            "start": [int(line_start[0]), int(line_start[1])],
            "end": [int(line_end[0]), int(line_end[1])],
            "thickness": thickness,
        }
        cal["pairs"] = pairs
        cal["fit"] = fit_type
        cal["polynomial_degree"] = poly_degree
        if len(pairs) >= 2:
            coeffs = fit_calibration(
                [tuple(p) for p in pairs],
                fit_type,
                poly_degree,
            )
            cal["coefficients"] = coeffs.tolist()
        try:
            save_spectrometer_config(cfg, config_path)
            status_label.set_text(f"Config saved to {config_path}")
        except Exception as e:
            status_label.set_text(f"Error: {e}")
        fig.canvas.draw_idle()

    ax_set_line = plt.axes([0.02, 0.02, 0.06, 0.12])
    ax_add_cal = plt.axes([0.09, 0.02, 0.09, 0.12])
    ax_fit_linear = plt.axes([0.19, 0.02, 0.05, 0.12])
    ax_fit_poly = plt.axes([0.25, 0.02, 0.07, 0.12])
    ax_save = plt.axes([0.33, 0.02, 0.07, 0.12])
    ax_thick = plt.axes([0.41, 0.02, 0.08, 0.12])
    ax_pixel = plt.axes([0.50, 0.02, 0.08, 0.12])
    ax_wl = plt.axes([0.59, 0.02, 0.12, 0.12])
    ax_pt = plt.axes([0.72, 0.02, 0.04, 0.12])
    ax_del = plt.axes([0.77, 0.02, 0.04, 0.12])
    ax_edit = plt.axes([0.82, 0.02, 0.04, 0.12])
    ax_update = plt.axes([0.87, 0.02, 0.05, 0.12])
    ax_wl_x = plt.axes([0.93, 0.02, 0.05, 0.12])

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

    def on_thickness_submit(text):
        nonlocal thickness
        try:
            t = int(text.strip())
            if 1 <= t <= 31:
                thickness = t
        except ValueError:
            pass

    def on_wl_x_toggle(label):
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

    def on_click(event):
        if event.inaxes == ax_img:
            on_image_click(event)
        elif event.inaxes == ax_spec:
            on_spectrum_click_handler(event)

    btn_set_line.on_clicked(set_line_click)
    btn_add_cal.on_clicked(add_calibration_click)
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
        ax_start_x: "Fine-tune start marker X position",
        ax_start_y: "Fine-tune start marker Y position",
        ax_end_x: "Fine-tune end marker X position",
        ax_end_y: "Fine-tune end marker Y position",
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
    }

    def on_hover(event):
        if event.inaxes in tooltip_axes:
            tooltip_annot.set_text(tooltip_axes[event.inaxes])
            tooltip_annot.xy = (event.x, event.y)
            tooltip_annot.set_visible(True)
        else:
            tooltip_annot.set_visible(False)
        fig.canvas.draw_idle()

    fig.canvas.mpl_connect("button_press_event", on_click)
    fig.canvas.mpl_connect("motion_notify_event", on_hover)

    refresh()
    plt.show()


if __name__ == "__main__":
    main()
