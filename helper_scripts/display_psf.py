#!/usr/bin/env python3
"""
Display PSF for Richardson–Lucy deconvolution diagnostics.

Shows PSF shape, peak position, centering status, and basic stats.
Use to verify PSF is suitable before enabling Richardson–Lucy.
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def center_psf(psf: np.ndarray) -> np.ndarray:
    """Roll PSF so peak is at center. Returns copy."""
    peak_idx = int(np.argmax(psf))
    center_idx = len(psf) // 2
    shift = center_idx - peak_idx
    return np.roll(psf, shift)


def main():
    """CLI entrypoint: load a saved PSF `.npy` file and display quality diagnostics.

    Inputs:
        Command-line args:
        - `psf_path`: path to `.npy` PSF file
        - `--no-plot`: print stats only (no matplotlib UI)
        - `--show-centered`: also plot a centered version of the PSF if misaligned
    Output:
        Prints PSF stats (peak/center offset/FWHM) to stdout and optionally shows a matplotlib plot.
    Transformation:
        Loads the PSF array, normalizes/validates shape, computes peak offset from the center,
        prints warnings if the PSF is not centered, and optionally renders the plot and a corrected curve.
    """
    parser = argparse.ArgumentParser(
        description="Display PSF from .npy file for Richardson–Lucy diagnostics."
    )
    parser.add_argument(
        "psf_path",
        nargs="?",
        default="psf.npy",
        help="Path to .npy PSF file (default: psf.npy)",
    )
    parser.add_argument(
        "--no-plot",
        action="store_true",
        help="Print stats only, no matplotlib plot",
    )
    parser.add_argument(
        "--show-centered",
        action="store_true",
        help="Also plot PSF after centering (peak at center)",
    )
    args = parser.parse_args()

    path = args.psf_path
    if not os.path.isfile(path):
        print(f"Error: File not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        arr = np.load(path)
        psf = np.asarray(arr, dtype=np.float64).ravel()
    except Exception as e:
        print(f"Error loading {path}: {e}", file=sys.stderr)
        sys.exit(1)

    if len(psf) < 3:
        print(f"Error: PSF too short (len={len(psf)})", file=sys.stderr)
        sys.exit(1)

    # Stats
    peak_idx = int(np.argmax(psf))
    center_idx = len(psf) // 2
    offset = peak_idx - center_idx
    s = psf.sum()
    fwhm_approx = _approx_fwhm(psf)

    print(f"PSF: {path}")
    print(f"  Length: {len(psf)}")
    print(f"  Sum: {s:.6f}" + (" (OK, normalized)" if 0.99 < s < 1.01 else " (WARNING: should be ~1)"))
    print(f"  Peak index: {peak_idx} (center would be {center_idx})")
    print(f"  Peak offset from center: {offset} px" + (" (OK)" if offset == 0 else " (WARNING: PSF not centered!)"))
    print(f"  Approx FWHM: {fwhm_approx:.1f} px")
    print()

    if offset != 0:
        print("  >>> Richardson–Lucy requires PSF with peak at center.")
        print("  >>> Non-centered PSF causes wavelength/intensity shift artifacts.")
        print("  >>> Fix: center PSF before use, or re-measure with symmetric ROI.")
        print()

    if args.no_plot:
        sys.exit(0)

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed; use --no-plot for stats only.", file=sys.stderr)
        sys.exit(0)

    fig, ax = plt.subplots(figsize=(10, 4))
    x = np.arange(len(psf))
    ax.plot(x, psf, "b-", label="PSF", linewidth=1.5)
    ax.axvline(center_idx, color="gray", linestyle="--", alpha=0.7, label="Center")
    ax.axvline(peak_idx, color="red", linestyle=":", alpha=0.8, label="Peak")
    if args.show_centered and offset != 0:
        psf_centered = center_psf(psf)
        ax.plot(x, psf_centered, "g--", alpha=0.7, label="PSF centered")
    ax.set_xlabel("Index")
    ax.set_ylabel("Value")
    ax.set_title(f"PSF: {os.path.basename(path)} (peak offset: {offset} px)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()


def _approx_fwhm(psf: np.ndarray) -> float:
    """Rough FWHM from peak; returns 0 if unclear."""
    peak = psf.max()
    if peak <= 0:
        return 0.0
    half = peak / 2
    above = psf >= half
    if not np.any(above):
        return 0.0
    indices = np.where(above)[0]
    return float(indices[-1] - indices[0] + 1)


if __name__ == "__main__":
    main()
