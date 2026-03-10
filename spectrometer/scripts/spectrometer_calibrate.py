#!/usr/bin/env python3
"""
Manage calibration pairs. Add pairs, set fit type, compute coefficients.
Input: spectrometer_config.json. Output: updated config with calibration.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.config import load_spectrometer_config, save_spectrometer_config
from lib.spectrum import fit_calibration


def main():
    ap = argparse.ArgumentParser(description="Spectrometer calibration")
    ap.add_argument("--calibration-id", default="default", help="Calibration ID")
    ap.add_argument("--add-pair", nargs=2, type=float, metavar=("PIXEL", "WAVELENGTH_NM"))
    ap.add_argument("--fit", choices=["linear", "polynomial"], default=None)
    ap.add_argument("--degree", type=int, default=2, help="Polynomial degree")
    ap.add_argument("--list", action="store_true", help="List calibrations")
    args = ap.parse_args()

    cfg = load_spectrometer_config()
    calibs = cfg.setdefault("calibrations", [])

    cal = next((c for c in calibs if c["id"] == args.calibration_id), None)
    if cal is None:
        cal = {"id": args.calibration_id, "pairs": [], "fit": "linear", "polynomial_degree": 2}
        calibs.append(cal)

    if args.add_pair:
        pixel, wl = float(args.add_pair[0]), float(args.add_pair[1])
        cal["pairs"].append([pixel, wl])
        cal["pairs"].sort(key=lambda p: p[0])

    if args.fit:
        cal["fit"] = args.fit
        cal["polynomial_degree"] = args.degree

    if args.list:
        for c in calibs:
            print(json.dumps(c, indent=2))
        return

    # Recompute coefficients
    if len(cal["pairs"]) >= 2:
        coeffs = fit_calibration(
            [tuple(p) for p in cal["pairs"]],
            cal.get("fit", "linear"),
            cal.get("polynomial_degree", 2),
        )
        cal["coefficients"] = coeffs.tolist()
        print(f"Calibration {cal['id']}: coefficients = {coeffs}")

    save_spectrometer_config(cfg)
    print("Config saved.")


if __name__ == "__main__":
    main()
