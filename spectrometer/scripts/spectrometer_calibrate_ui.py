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

    fig = plt.figure(figsize=(14, 6))
    gs = fig.add_gridspec(
        2, 2,
        height_ratios=[4, 1],
        width_ratios=[1, 1],
        left=0.01, right=0.99, top=0.93, bottom=0.17,
        hspace=0.10, wspace=0.04,
    )

    ax_img = fig.add_subplot(gs[0, 0])
    ax_spec = fig.add_subplot(gs[0, 1])
    ax_btns = fig.add_subplot(gs[1, :])

    ax_img.set_title("Camera image — click two points to set line")
    ax_spec.set_title("Spectrum (intensity vs pixel) — click to add calibration point")
    ax_img.set_axis_off()
    ax_btns.set_axis_off()

    img_display = ax_img.imshow(frame, cmap="gray")
    line_artist, = ax_img.plot([], [], "r-", linewidth=2)
    start_marker, = ax_img.plot([], [], "go", markersize=10)
    end_marker, = ax_img.plot([], [], "ro", markersize=10)

    spec_line, = ax_spec.plot([], [], "b-")
    cal_markers, = ax_spec.plot([], [], "r.", markersize=12)

    def update_line_display():
        line_artist.set_data([line_start[0], line_end[0]], [line_start[1], line_end[1]])
        start_marker.set_data([line_start[0]], [line_start[1]])
        end_marker.set_data([line_end[0]], [line_end[1]])
        fig.canvas.draw_idle()

    def update_spectrum():
        start = (int(line_start[0]), int(line_start[1]))
        end = (int(line_end[0]), int(line_end[1]))
        intensities = extract_line_profile(frame, start, end, thickness)
        pixels = np.arange(len(intensities))
        spec_line.set_data(pixels, intensities)
        ax_spec.relim()
        ax_spec.autoscale_view()
        if pairs:
            px = [p[0] for p in pairs]
            py = []
            for pi in px:
                idx = int(round(pi))
                if 0 <= idx < len(intensities):
                    py.append(intensities[idx])
                else:
                    py.append(0)
            cal_markers.set_data(px, py)
        else:
            cal_markers.set_data([], [])
        fig.canvas.draw_idle()

    def refresh():
        update_line_display()
        update_spectrum()

    def on_image_click(event):
        if event.inaxes != ax_img or event.xdata is None:
            return
        nonlocal line_click_count
        x, y = int(round(event.xdata)), int(round(event.ydata))
        if line_click_count == 0:
            line_start[0], line_start[1] = x, y
            line_click_count = 1
            ax_img.set_title("Click end point of line")
        else:
            line_end[0], line_end[1] = x, y
            line_click_count = 0
            ax_img.set_title("Camera image — click two points to set line")
        refresh()

    def set_line_click(_):
        nonlocal line_click_count, add_calibration_mode, pending_pixel
        line_click_count = 0
        add_calibration_mode = False
        pending_pixel = None
        ax_img.set_title("Camera image — click two points to set line")
        ax_spec.set_title("Spectrum (intensity vs pixel) — click to add calibration point")
        status_label.set_text("")
        refresh()

    def add_calibration_click(_):
        nonlocal add_calibration_mode
        add_calibration_mode = True
        ax_spec.set_title("Spectrum — click a point, then enter wavelength in box below")
        fig.canvas.draw_idle()

    def on_spectrum_click_handler(event):
        nonlocal pending_pixel
        if event.inaxes != ax_spec or event.xdata is None:
            return
        if not add_calibration_mode:
            return
        pending_pixel = float(event.xdata)
        status_label.set_text(f"Pixel {pending_pixel:.1f} — enter wavelength (nm) below, press Enter")
        wl_box.set_val("")
        fig.canvas.draw_idle()

    def on_wavelength_submit(text):
        nonlocal pending_pixel
        if pending_pixel is None:
            return
        try:
            wl = float(text.strip())
            if 200 <= wl <= 1200:
                pairs.append([pending_pixel, wl])
                pairs.sort(key=lambda p: p[0])
                pending_pixel = None
                status_label.set_text("")
                refresh()
        except ValueError:
            pass

    def fit_linear_click(_):
        nonlocal fit_type
        fit_type = "linear"
        fit_label.set_text(f"Fit: {fit_type}")

    def fit_poly_click(_):
        nonlocal fit_type
        fit_type = "polynomial"
        fit_label.set_text(f"Fit: {fit_type}")

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
    ax_thick = plt.axes([0.45, 0.02, 0.14, 0.12])
    ax_wl = plt.axes([0.64, 0.02, 0.16, 0.12])

    btn_set_line = widgets.Button(ax_set_line, "Set line")
    btn_add_cal = widgets.Button(ax_add_cal, "Add calibration point")
    btn_fit_linear = widgets.Button(ax_fit_linear, "Linear")
    btn_fit_poly = widgets.Button(ax_fit_poly, "Polynomial")
    btn_save = widgets.Button(ax_save, "Save config")
    thick_box = widgets.TextBox(ax_thick, "Thick ", initial=str(thickness))
    wl_box = widgets.TextBox(ax_wl, "λ (nm) ", initial="")

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

    fig.canvas.mpl_connect("button_press_event", on_click)

    update_line_display()
    update_spectrum()
    plt.show()


if __name__ == "__main__":
    main()
