#!/usr/bin/env python3
"""
Acquire dark or flat frames for spectrometer calibration.
Usage: acquire_dark_flat.py (dark|flat) num_frames output_path

Example:
  acquire_dark_flat.py dark 20 /home/raspberry/spectrometer/calibration/dark.npy
  acquire_dark_flat.py flat 20 /home/raspberry/spectrometer/calibration/flat.npy

Prerequisite: RTSP stream OFF.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.camera_capture import capture_frames_averaged


def main():
    """CLI entrypoint: acquire and save an averaged dark/flat frame.

    Inputs:
        Command-line args: `sys.argv[1]` is `"dark"` or `"flat"`, `sys.argv[2]` is number of frames to average,
        and `sys.argv[3]` is the output `.npy` path.
    Output:
        None (writes the averaged frame to `out_path` using `np.save` and exits).
    Transformation:
        - Validates CLI arguments.
        - Prompts the user to block light or illuminate uniformly.
        - Captures `n` frames, averages them via `capture_frames_averaged(n)`.
        - Saves the averaged frame array to disk.
    """
    if len(sys.argv) != 4:
        print("Usage: acquire_dark_flat.py (dark|flat) num_frames output_path", file=sys.stderr)
        sys.exit(1)

    mode = sys.argv[1].lower()
    if mode not in ("dark", "flat"):
        print("Mode must be 'dark' or 'flat'", file=sys.stderr)
        sys.exit(1)

    try:
        n = int(sys.argv[2])
    except ValueError:
        print("num_frames must be an integer", file=sys.stderr)
        sys.exit(1)

    if n < 2:
        print("num_frames should be >= 2 for averaging", file=sys.stderr)
        sys.exit(1)

    out_path = sys.argv[3]

    if mode == "dark":
        print("Block all light to the spectrometer, then press Enter...")
        input()
    else:
        print("Illuminate with uniform light (ensure no saturation). Press Enter to capture...")
        input()

    print(f"Capturing {n} frames...")
    averaged = capture_frames_averaged(n)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    np.save(out_path, averaged)
    print(f"Saved to {out_path} (shape {averaged.shape})")


if __name__ == "__main__":
    main()
