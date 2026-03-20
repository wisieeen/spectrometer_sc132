#!/usr/bin/env python3
"""
Shared camera capture. Opens /dev/video0, configures via v4l2-ctl and I2C, captures frame(s).
Prerequisite: rtsp-camera.service and mediamtx.service must be STOPPED (V4L2 exclusive).
Shutter is NOT clamped to FPS when used for single-frame capture (long exposure allowed).
"""
import json
import os
import subprocess
import sys
from typing import Optional

import cv2
import numpy as np

from lib.env_config import load_env, load_camera_config


def _parse_resolution(res: str) -> tuple[int, int]:
    """Parse a camera resolution string formatted as `WIDTHxHEIGHT`.

    Inputs:
        res: Resolution string like `"1080x640"`.
    Output:
        Tuple `(width, height)` as positive integers.
    Transformation:
        Validates formatting, splits by `"x"`, converts to `int`, and rejects invalid/negative values.
    """
    if not res or "x" not in res:
        raise ValueError(f"resolution must be WxH (e.g. 1080x640), got {res!r}")
    parts = res.strip().split("x")
    if len(parts) != 2:
        raise ValueError(f"resolution must be WxH, got {res!r}")
    try:
        w, h = int(parts[0]), int(parts[1])
    except ValueError:
        raise ValueError(f"resolution W and H must be integers, got {res!r}")
    if w < 1 or h < 1:
        raise ValueError(f"resolution W and H must be >= 1, got {res!r}")
    return w, h


def _get_capture_context():
    """
    Build the capture context needed by all capture functions.

    Inputs:
        None (reads env + camera config from disk using `load_env()` / `load_camera_config()`).
    Output:
        `(env, cfg, device, w, h, bpl, stride_w, pixel_format)` where:
            - `device`: video device path (e.g. `/dev/video0`)
            - `w`, `h`: parsed resolution width/height
            - `bpl`: bytes-per-line reported by `v4l2-ctl`
            - `stride_w`: effective stride width in pixels (may exceed `w`)
            - `pixel_format`: normalized pixel format string (`Y8`, `Y10`, or `Y10P`)
    Transformation:
        Ensures RTSP services are stopped, configures the V4L2 device using the configured ROI/FPS/i2c,
        then computes stride/pixel-format details used by raw capture paths.
    """
    env = load_env()
    cfg = load_camera_config(env)
    _ensure_stream_stopped(env)
    _configure_device(env, cfg)

    device = env.get("device", {}).get("video", "/dev/video0")
    res = cfg.get("resolution", "1080x640")
    w, h = _parse_resolution(res)
    bpl, stride_w = _get_stride_info(env, cfg)
    pixel_format = str(cfg.get("pixel_format", "Y8")).strip().upper()
    if pixel_format in ("GREY",):
        pixel_format = "Y8"
    if pixel_format not in ("Y8", "Y10", "Y10P"):
        pixel_format = "Y8"
    return env, cfg, device, w, h, bpl, stride_w, pixel_format


def _ensure_stream_stopped(env):
    """Ensure RTSP pipeline services are stopped before touching V4L2.

    Inputs:
        env: Environment dict containing `services.rtsp_camera` and `services.mediamtx` entries.
    Output:
        None (terminates the process with a message when the services are active).
    Transformation:
        Calls `systemctl is-active` for each service; if either is `active`, prints an error to stderr
        and exits with status 1 to avoid V4L2 conflicts.
    """
    for svc in env.get("services", {}).get("rtsp_camera", "rtsp-camera.service"), env.get(
        "services", {}
    ).get("mediamtx", "mediamtx.service"):
        result = subprocess.run(
            ["systemctl", "is-active", svc],
            capture_output=True,
            text=True,
        )
        if result.stdout.strip() == "active":
            print(
                f"Error: {svc} is active. Stop RTSP stream first (e.g. publish OFF to rtsp topic).",
                file=sys.stderr,
            )
            sys.exit(1)


def _get_stride_info(env, cfg) -> tuple[int, int]:
    """
    Query bytes-per-line and stride width (pixels) from the V4L2 device.

    Inputs:
        env: Environment dict (contains `device.video`).
        cfg: Camera configuration dict (contains `pixel_format`).
    Output:
        `(bytes_per_line, stride_width_px)`. `stride_width_px` may exceed the configured width
        when the driver adds row padding.
    Transformation:
        Runs `v4l2-ctl --get-fmt-video`, parses the `Bytes per Line` field, then derives stride width
        depending on pixel format (`Y8` uses 1 byte/pixel; `Y10` and `Y10P` use packed formats).
    """
    device = env.get("device", {}).get("video", "/dev/video0")
    pixel_format = cfg.get("pixel_format", "Y8")
    result = subprocess.run(
        ["v4l2-ctl", "-d", device, "--get-fmt-video"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return 0, 0
    bpl = 0
    for line in result.stdout.splitlines():
        if "Bytes per Line" in line:
            bpl = int(line.split()[-1])
            break
    if bpl == 0:
        return 0, 0
    if pixel_format in ("Y8", "GREY", "grey"):
        stride_w = bpl
    elif pixel_format == "Y10":
        stride_w = bpl // 2
    elif pixel_format == "Y10P":
        stride_w = bpl * 4 // 5
    else:
        stride_w = bpl
    return bpl, stride_w


def _configure_device(env, cfg):
    """Configure the V4L2 device and optionally apply I2C exposure/gain.

    Inputs:
        env: Environment dict (contains `device.video`, `device.i2c_bus`, and `paths.i2c_tool`).
        cfg: Camera config dict (contains `resolution`, `fps`, `shutter`, `gain`, `pixel_format`).
    Output:
        None (side-effect: configures V4L2 and the device via `v4l2-ctl` / I2C tool).
    Transformation:
        - Sets ROI to (0,0), applies width/height/pixelformat and frame rate.
        - Converts resolution using `_parse_resolution`.
        - Applies I2C `expmode`/`gainmode` and optionally `metime`/`mgain` if the I2C tool exists.
        - Intentionally does NOT clamp shutter to FPS because this path is used for single-frame capture.
    """
    device = env.get("device", {}).get("video", "/dev/video0")
    i2c_tool = env.get("paths", {}).get("i2c_tool")
    i2c_bus = str(env.get("device", {}).get("i2c_bus", "10"))
    i2c_dir = os.path.dirname(i2c_tool) if i2c_tool else "."

    w, h = _parse_resolution(cfg.get("resolution", "1080x640"))
    fps = max(1, min(120, int(cfg.get("fps", 5))))
    shutter = max(0, int(cfg.get("shutter", 0)))
    gain = cfg.get("gain", 0.0)
    pixel_format = str(cfg.get("pixel_format", "Y8")).strip()
    v4l2_fmt = "GREY" if pixel_format in ("Y8", "GREY", "grey") else "Y10 " if pixel_format == "Y10" else "Y10P"

    subprocess.run(["v4l2-ctl", "-d", device, "--set-ctrl", "roi_x=0"], check=False)
    subprocess.run(["v4l2-ctl", "-d", device, "--set-ctrl", "roi_y=0"], check=False)
    subprocess.run(
        [
            "v4l2-ctl",
            "-d",
            device,
            "--set-fmt-video",
            f"width={w},height={h},pixelformat={v4l2_fmt}",
        ],
        check=False,
    )
    subprocess.run(
        ["v4l2-ctl", "-d", device, "--set-ctrl", f"frame_rate={fps}"],
        check=False,
    )

    if i2c_tool and os.path.isfile(i2c_tool) and os.access(i2c_tool, os.X_OK):
        subprocess.run(
            [i2c_tool, "-w", "expmode", "0", "-b", i2c_bus],
            cwd=i2c_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        subprocess.run(
            [i2c_tool, "-w", "gainmode", "0", "-b", i2c_bus],
            cwd=i2c_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if shutter > 0:
            subprocess.run(
                [i2c_tool, "-w", "metime", str(shutter), "-b", i2c_bus],
                cwd=i2c_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        if gain is not None:
            subprocess.run(
                [i2c_tool, "-w", "mgain", str(gain), "-b", i2c_bus],
                cwd=i2c_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )


def _capture_raw_y8(env, cfg, w, h, bpl, stride_w, num_frames: int) -> np.ndarray:
    """
    Capture raw Y8 frames using `v4l2-ctl` and return only the last frame.

    Inputs:
        env: Environment dict (contains `device.video`).
        cfg: Camera config dict (currently unused in this function but kept for API symmetry).
        w, h: Requested output width/height.
        bpl: Bytes per line (from `_get_stride_info`).
        stride_w: Stride width in pixels (may exceed `w` due to padding).
        num_frames: Number of frames to capture via `--stream-count`.
    Output:
        Last captured frame as a 2D NumPy array (dtype depends on downstream; raw capture uses uint8).
    Transformation:
        Delegates to `_capture_raw_y8_all(...)`, then returns the final entry (or `None` if no frames).
    """
    frames = _capture_raw_y8_all(env, cfg, w, h, bpl, stride_w, num_frames)
    return frames[-1] if frames else None


def _read_exact(stream, n: int) -> Optional[bytes]:
    """Read exactly `n` bytes from a file-like stream.

    Inputs:
        stream: A readable binary stream (e.g. `proc.stdout`).
        n: Number of bytes to read.
    Output:
        Byte string of length `n`, or None if the stream ends early (EOF).
    Transformation:
        Accumulates chunks until the requested byte count is reached.
    """
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def _capture_raw_y8_averaged(env, cfg, w, h, bpl, stride_w, num_frames: int) -> np.ndarray | None:
    """
    Capture raw Y8 frames and return their average as float64.

    Inputs:
        env: Environment dict (contains `device.video`).
        cfg: Camera config dict (currently unused in this function but kept for API symmetry).
        w, h: Requested output width/height.
        bpl: Bytes per line.
        stride_w: Stride width in pixels (may exceed `w` due to padding).
        num_frames: Number of frames to capture.
    Output:
        Averaged frame as float64 NumPy array (shape `(h, w)`), or None on failure/timeout.
    Transformation:
        Streams frames from `v4l2-ctl --stream-to=-`, crops each frame to `(h, w)`,
        accumulates in float64, and returns `accum / num_frames`.
    """
    device = env.get("device", {}).get("video", "/dev/video0")
    frame_bytes = bpl * h

    proc = subprocess.Popen(
        [
            "v4l2-ctl",
            "-d",
            device,
            "--stream-mmap",
            "--stream-count",
            str(num_frames),
            "--stream-to=-",
        ],
        stdout=subprocess.PIPE,
        bufsize=frame_bytes,
    )
    try:
        accum = None
        for _ in range(num_frames):
            raw = _read_exact(proc.stdout, frame_bytes)
            if raw is None or len(raw) < frame_bytes:
                return None
            frame = np.frombuffer(raw, dtype=np.uint8).reshape(h, bpl)[:, :w].copy()
            if accum is None:
                accum = np.zeros(frame.shape, dtype=np.float64)
            accum += frame
        proc.wait(timeout=5)
        if accum is None:
            return None
        return (accum / num_frames).astype(np.float64)
    except (subprocess.TimeoutExpired, OSError):
        proc.kill()
        proc.wait()
        return None


def _capture_raw_y10_averaged(env, cfg, w, h, bpl, stride_w, num_frames: int) -> np.ndarray | None:
    """
    Capture raw Y10 frames and return their average as float64.

    Inputs:
        env: Environment dict (contains `device.video`).
        cfg: Camera config dict (currently unused in this function but kept for API symmetry).
        w, h: Requested output width/height.
        bpl: Bytes per line.
        stride_w: Stride width in pixels (may differ from `w` for Y10 packing).
        num_frames: Number of frames to capture.
    Output:
        Averaged frame as float64 NumPy array (shape `(h, w)`), or None on failure/timeout.
    Transformation:
        Streams frames from `v4l2-ctl`, interprets raw bytes as uint16, crops to `(h, w)`,
        accumulates in float64, and returns `accum / num_frames`.
    """
    device = env.get("device", {}).get("video", "/dev/video0")
    frame_bytes = bpl * h

    proc = subprocess.Popen(
        [
            "v4l2-ctl",
            "-d",
            device,
            "--stream-mmap",
            "--stream-count",
            str(num_frames),
            "--stream-to=-",
        ],
        stdout=subprocess.PIPE,
        bufsize=frame_bytes,
    )
    try:
        accum = None
        for _ in range(num_frames):
            raw = _read_exact(proc.stdout, frame_bytes)
            if raw is None or len(raw) < frame_bytes:
                return None
            frame = np.frombuffer(raw, dtype=np.uint16).reshape(h, stride_w)[:, :w].copy()
            if accum is None:
                accum = np.zeros(frame.shape, dtype=np.float64)
            accum += frame.astype(np.float64)
            del frame
        proc.wait(timeout=5)
        if accum is None:
            return None
        return (accum / num_frames).astype(np.float64)
    except (subprocess.TimeoutExpired, OSError):
        proc.kill()
        proc.wait()
        return None


def _capture_raw_y8_all(env, cfg, w, h, bpl, stride_w, num_frames: int) -> list:
    """Capture all Y8 frames using `v4l2-ctl` and return them as a list.

    Inputs:
        env: Environment dict (contains `device.video`).
        cfg: Camera config dict (currently unused in this function but kept for API symmetry).
        w, h: Requested output width/height.
        bpl: Bytes per line.
        stride_w: Stride width in pixels (may exceed `w` due to padding).
        num_frames: Number of frames to capture.
    Output:
        List of frames (each a 2D NumPy array of shape `(h, w)`), or [] on failure.
    Transformation:
        Runs `v4l2-ctl --stream-mmap --stream-to=-`, slices the output buffer into per-frame chunks,
        reshapes to `(h, bpl)`/stride layout, then crops to `(h, w)` for each frame.
    """
    device = env.get("device", {}).get("video", "/dev/video0")
    frame_bytes = bpl * h

    proc = subprocess.run(
        [
            "v4l2-ctl",
            "-d",
            device,
            "--stream-mmap",
            "--stream-count",
            str(num_frames),
            "--stream-to=-",
        ],
        capture_output=True,
        timeout=30,
    )
    if proc.returncode != 0 or len(proc.stdout) < frame_bytes * num_frames:
        return []

    frames = []
    for i in range(num_frames):
        offset = frame_bytes * i
        raw = proc.stdout[offset : offset + frame_bytes]
        frame = np.frombuffer(raw, dtype=np.uint8).reshape(h, bpl)[:, :w].copy()
        frames.append(frame)
    return frames


def _capture_raw_y10(env, cfg, w, h, bpl, stride_w, num_frames: int) -> np.ndarray:
    """
    Capture raw Y10 frames via `v4l2-ctl` and return only the last frame.

    Inputs:
        env: Environment dict (contains `device.video`).
        cfg: Camera config dict (currently unused in this function but kept for API symmetry).
        w, h: Requested output width/height.
        bpl: Bytes per line.
        stride_w: Stride width in pixels used to reshape the raw buffer.
        num_frames: Number of frames to capture.
    Output:
        Last captured frame as a 2D NumPy array (uint16), or None if capture fails.
    Transformation:
        Delegates to `_capture_raw_y10_all(...)` and returns the last frame.
    """
    frames = _capture_raw_y10_all(env, cfg, w, h, bpl, stride_w, num_frames)
    return frames[-1] if frames else None


def _capture_raw_y10_all(env, cfg, w, h, bpl, stride_w, num_frames: int) -> list:
    """Capture all Y10 frames via `v4l2-ctl` and return them as a list.

    Inputs:
        env: Environment dict (contains `device.video`).
        cfg: Camera config dict (currently unused in this function but kept for API symmetry).
        w, h: Requested output width/height.
        bpl: Bytes per line.
        stride_w: Stride width in pixels (used in reshape).
        num_frames: Number of frames to capture.
    Output:
        List of frames (2D NumPy arrays of uint16, shape `(h, w)`), or [] on failure.
    Transformation:
        Runs `v4l2-ctl --stream-mmap --stream-to=-`, slices the raw buffer into per-frame chunks,
        interprets as uint16, reshapes to `(h, stride_w)`, and crops to `(h, w)`.
    """
    device = env.get("device", {}).get("video", "/dev/video0")
    frame_bytes = bpl * h

    proc = subprocess.run(
        [
            "v4l2-ctl",
            "-d",
            device,
            "--stream-mmap",
            "--stream-count",
            str(num_frames),
            "--stream-to=-",
        ],
        capture_output=True,
        timeout=30,
    )
    if proc.returncode != 0 or len(proc.stdout) < frame_bytes * num_frames:
        return []

    frames = []
    for i in range(num_frames):
        offset = frame_bytes * i
        raw = proc.stdout[offset : offset + frame_bytes]
        frame = np.frombuffer(raw, dtype=np.uint16).reshape(h, stride_w)[:, :w].copy()
        frames.append(frame)
    return frames


def capture_frame(num_frames: int = 1) -> np.ndarray:
    """
    Capture one frame (or multiple and return the last) from `/dev/video0`.

    Inputs:
        num_frames: Number of frames to request; if > 1, the function captures them sequentially and returns the last frame.
    Output:
        2D grayscale frame as a NumPy array (shape `(height, width)`).
    Transformation:
        - Loads capture context (env/config), ensures RTSP services are stopped, configures V4L2/I2C.
        - Chooses raw capture paths for Y8 stride-padding and for Y10 (because OpenCV mis-decodes Y10).
        - Otherwise uses OpenCV `VideoCapture`, optionally crops for stride mismatches, and converts to grayscale if needed.
    """
    env, cfg, device, w, h, bpl, stride_w, pixel_format = _get_capture_context()

    # Y10: OpenCV cannot decode it (misinterprets as BGR → garbage). Always use raw capture.
    if pixel_format == "Y10" and stride_w > 0:
        frame = _capture_raw_y10(env, cfg, w, h, bpl, stride_w, num_frames)
        if frame is not None:
            return frame
        print("Raw Y10 capture failed; cannot fall back to OpenCV (Y10 unsupported)", file=sys.stderr)
        sys.exit(1)

    # Y8: when stride != width, OpenCV misinterprets buffer; use raw capture
    if pixel_format in ("Y8", "GREY", "grey") and stride_w > 0 and stride_w != w:
        frame = _capture_raw_y8(env, cfg, w, h, bpl, stride_w, num_frames)
        if frame is not None:
            return frame

    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        print("Failed to open video device", file=sys.stderr)
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)

    frame = None
    for _ in range(num_frames):
        ret, frame = cap.read()
        if not ret:
            break
    cap.release()

    if frame is None:
        print("Failed to read frame", file=sys.stderr)
        sys.exit(1)

    # Fallback crop if we used OpenCV but had stride (e.g. _get_stride_info failed)
    if stride_w > 0 and stride_w != w and frame.shape[1] >= w:
        frame = frame[:, :w].copy()

    # Ensure 2D grayscale for downstream (Y10 via OpenCV may return 3D)
    if len(frame.shape) == 3:
        if frame.shape[2] == 1:
            frame = frame[:, :, 0]
        else:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    return frame


def capture_frames(n: int) -> list:
    """
    Capture `n` consecutive grayscale frames from `/dev/video0`.

    Inputs:
        n: Number of frames to capture.
    Output:
        List of `n` frames, where each frame is a 2D NumPy array (shape `(height, width)`).
    Transformation:
        Uses the same capture context/configuration as `capture_frame()`, chooses raw capture paths
        when required (Y10 or stride-padding), otherwise uses OpenCV `VideoCapture` and crops/gray-converts
        each frame to the configured width.
    """
    if n <= 0:
        return []
    if n == 1:
        return [capture_frame(1)]

    env, cfg, device, w, h, bpl, stride_w, pixel_format = _get_capture_context()

    if pixel_format == "Y10" and stride_w > 0:
        frames = _capture_raw_y10_all(env, cfg, w, h, bpl, stride_w, n)
        if frames:
            return frames
        print("Raw Y10 capture failed; cannot fall back to OpenCV (Y10 unsupported)", file=sys.stderr)
        sys.exit(1)

    if pixel_format in ("Y8", "GREY", "grey") and stride_w > 0 and stride_w != w:
        frames = _capture_raw_y8_all(env, cfg, w, h, bpl, stride_w, n)
        if frames:
            return frames

    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        print("Failed to open video device", file=sys.stderr)
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)

    frames = []
    for _ in range(n):
        ret, frame = cap.read()
        if not ret:
            break
        if stride_w > 0 and stride_w != w and frame.shape[1] >= w:
            frame = frame[:, :w].copy()
        if len(frame.shape) == 3:
            frame = frame[:, :, 0] if frame.shape[2] == 1 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        frames.append(frame)

    cap.release()

    if len(frames) < n:
        print("Failed to read all frames", file=sys.stderr)
        sys.exit(1)

    return frames


def capture_frames_averaged(n: int) -> np.ndarray:
    """
    Capture `n` consecutive frames and return their average as a float64 frame.

    Inputs:
        n: Number of frames to capture; must be >= 1.
    Output:
        Averaged frame as a float64 NumPy array (shape `(height, width)`).
    Transformation:
        - For Y10 stride padding or Y8 stride-padding cases, uses streaming raw capture functions to average incrementally.
        - Otherwise uses OpenCV to capture frames, accumulates in float64, and returns `accum / count`.
    """
    if n <= 0:
        raise ValueError("n must be >= 1")
    if n == 1:
        frame = capture_frame(1)
        return frame.astype(np.float64)

    env, cfg, device, w, h, bpl, stride_w, pixel_format = _get_capture_context()

    if pixel_format == "Y10" and stride_w > 0:
        frame = _capture_raw_y10_averaged(env, cfg, w, h, bpl, stride_w, n)
        if frame is not None:
            return frame
        print("Raw Y10 capture failed; cannot fall back to OpenCV (Y10 unsupported)", file=sys.stderr)
        sys.exit(1)

    if pixel_format in ("Y8", "GREY", "grey") and stride_w > 0 and stride_w != w:
        frame = _capture_raw_y8_averaged(env, cfg, w, h, bpl, stride_w, n)
        if frame is not None:
            return frame

    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        print("Failed to open video device", file=sys.stderr)
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)

    accum = None
    count = 0
    for _ in range(n):
        ret, frame = cap.read()
        if not ret:
            break
        if stride_w > 0 and stride_w != w and frame.shape[1] >= w:
            frame = frame[:, :w].copy()
        if len(frame.shape) == 3:
            frame = frame[:, :, 0] if frame.shape[2] == 1 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if accum is None:
            accum = np.zeros(frame.shape, dtype=np.float64)
        accum += frame.astype(np.float64)
        count += 1
    cap.release()

    if count < n:
        print("Failed to read all frames", file=sys.stderr)
        sys.exit(1)

    return (accum / count).astype(np.float64)


if __name__ == "__main__":
    frame = capture_frame()
    print(f"Captured shape: {frame.shape}, dtype: {frame.dtype}")
