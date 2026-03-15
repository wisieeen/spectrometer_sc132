#!/usr/bin/env python3
"""
Live preview for line placement. Stops RTSP stream, runs preview, saves line definitions.
Headless: saves frame to file for remote viewing; user submits coordinates via config/MQTT.
With display: uses cv2.imshow for interactive placement.
"""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.camera_capture import capture_frame

PREVIEW_OUTPUT = os.environ.get("SPECTROMETER_PREVIEW_OUTPUT", "/tmp/spectrometer_preview.png")


def main():
    # Capture single frame (stream must be off)
    frame = capture_frame()
    # Y10 raw returns uint16 (0-1023); PNG expects 8-bit (0-255) for correct display
    if frame.dtype == np.uint16:
        frame = (frame.astype(np.float32) * 255 / 1023).clip(0, 255).astype(np.uint8)
    out_path = PREVIEW_OUTPUT
    cv2.imwrite(out_path, frame)
    print(f"Preview saved to {out_path}. Use this to define line coordinates.")
    print("Edit spectrometer_config.json channels[].line: start, end, thickness.")
    print("Or run with --interactive if display available (e.g. VNC).")


if __name__ == "__main__":
    main()
