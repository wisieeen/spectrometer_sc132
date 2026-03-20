#!/usr/bin/env python3
"""
Measure PSF from a narrow emission line for Richardson–Lucy deconvolution.

Prerequisite: Illuminate spectrometer with a narrow line (laser, LED, calibration lamp).
RTSP stream must be OFF.

Output: Ready-to-use .npy file (1D array, normalized to sum=1).
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.config import load_spectrometer_config, get_processing_cfg
from lib.signal_processing import apply_dark_flat_frame, load_dark_flat
from lib.spectrum import extract_line_profile
from scripts.camera_capture import capture_frame, capture_frames_averaged




def _extract_psf_from_profile(profile: np.ndarray, baseline_frac: float = 0.1) -> np.ndarray:
    """
    Convert line profile to PSF: subtract baseline, clip, normalize.
    baseline_frac: fraction of profile at each end to estimate baseline (default 10%).
    """
    profile = np.asarray(profile, dtype=np.float64).ravel()
    if len(profile) < 3:
        raise ValueError("Profile too short")
    n = len(profile)
    edge = max(1, int(n * baseline_frac))
    baseline = np.mean(np.concatenate([profile[:edge], profile[-edge:]]))
    psf = np.clip(profile - baseline, 0, None)
    s = psf.sum()
    if s <= 0:
        raise ValueError("Profile has no positive signal after baseline subtraction")
    psf /= s
    return psf


def _center_and_crop_psf(psf: np.ndarray, half_width: int = 50) -> np.ndarray:
    """
    Center PSF (peak at center) and crop symmetrically to odd length 2*half_width+1.
    Pads with zeros if peak is near edge.
    """
    peak_idx = int(np.argmax(psf))
    n = len(psf)
    left = max(0, peak_idx - half_width)
    right = min(n - 1, peak_idx + half_width)
    cropped = psf[left : right + 1].astype(np.float64)
    pad_left = half_width - (peak_idx - left)
    pad_right = half_width - (right - peak_idx)
    if pad_left > 0 or pad_right > 0:
        cropped = np.pad(cropped, (pad_left, pad_right), mode="constant", constant_values=0.0)
    s = cropped.sum()
    if s <= 0:
        raise ValueError("PSF has no signal after crop")
    cropped /= s
    return cropped


def main():
    parser = argparse.ArgumentParser(
        description="Measure PSF from narrow emission line. Output: .npy file for Richardson–Lucy."
    )
    parser.add_argument(
        "-o", "--output",
        default="psf.npy",
        help="Output path for .npy file (default: psf.npy)",
    )
    parser.add_argument(
        "-c", "--channel",
        default=0,
        type=int,
        help="Channel index (default: 0)",
    )
    parser.add_argument(
        "-n", "--frames",
        type=int,
        default=None,
        help="Number of frames to average (default: from config or 10)",
    )
    parser.add_argument(
        "--no-dark-flat",
        action="store_true",
        help="Skip dark/flat correction",
    )
    parser.add_argument(
        "-f", "--frame",
        metavar="PATH",
        help="Use existing frame from .npy file instead of capturing",
    )
    parser.add_argument(
        "--baseline-frac",
        type=float,
        default=0.1,
        help="Fraction of profile ends for baseline estimate (default: 0.1)",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="Path to spectrometer_config.json (default: from env or ./spectrometer_config.json)",
    )
    args = parser.parse_args()

    spec_cfg = load_spectrometer_config(args.config)
    channels = [c for c in spec_cfg.get("channels", []) if isinstance(c, dict) and "id" in c and c.get("line")]
    if not channels:
        print("Error: No channels with line defined in spectrometer_config.json", file=sys.stderr)
        sys.exit(1)

    idx = args.channel
    if idx < 0 or idx >= len(channels):
        print(f"Error: Channel index {idx} out of range (0..{len(channels)-1})", file=sys.stderr)
        sys.exit(1)

    ch = channels[idx]
    line = ch["line"]
    try:
        start = (int(line["start"][0]), int(line["start"][1]))
        end = (int(line["end"][0]), int(line["end"][1]))
        thickness = max(1, min(100, int(line.get("thickness", 5))))
    except (TypeError, ValueError, IndexError, KeyError) as e:
        print(f"Error: Invalid line config for channel {ch.get('id')}: {e}", file=sys.stderr)
        sys.exit(1)

    if args.frame:
        if not os.path.isfile(args.frame):
            print(f"Error: Frame file not found: {args.frame}", file=sys.stderr)
            sys.exit(1)
        frame = np.load(args.frame).astype(np.float64)
        if frame.ndim == 3:
            frame = frame[:, :, 0] if frame.shape[2] == 1 else np.mean(frame, axis=2)
    else:
        proc = get_processing_cfg(spec_cfg)
        n_frames, dark_path, flat_path = proc["frame_average_n"], proc["dark_frame_path"], proc["flat_frame_path"]
        n_frames = args.frames if args.frames is not None else n_frames
        dark, flat = (None, None) if args.no_dark_flat else load_dark_flat(dark_path, flat_path)
        print(f"Capturing {n_frames} frame(s)...", file=sys.stderr)
        if n_frames > 1:
            frame = capture_frames_averaged(n_frames)
        else:
            frame = capture_frame()
            frame = frame.astype(np.float64)
        if not args.no_dark_flat and (dark is not None or flat is not None):
            frame = apply_dark_flat_frame(frame, dark, flat)

    profile = extract_line_profile(frame, start, end, thickness)
    if len(profile) < 3:
        print("Error: Extracted profile too short", file=sys.stderr)
        sys.exit(1)

    try:
        psf = _extract_psf_from_profile(profile, baseline_frac=args.baseline_frac)
        psf = _center_and_crop_psf(psf, half_width=50)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    out_path = args.output
    np.save(out_path, psf)
    print(f"PSF saved: {out_path} (length={len(psf)}, sum={psf.sum():.6f})")
    print(f"Set richardson_lucy_psf_path to: {os.path.abspath(out_path)}")


if __name__ == "__main__":
    main()
