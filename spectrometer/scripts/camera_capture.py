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
    """Parse 'WxH' resolution. Raises ValueError if invalid."""
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
    Load env and camera config, ensure stream stopped, configure device.
    Returns (env, cfg, device, w, h, bpl, stride_w, pixel_format).
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
    """Check that rtsp-camera and mediamtx are stopped. Exit with message if not."""
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
    Query bytes-per-line and stride width (pixels) from v4l2-ctl.
    Returns (bytes_per_line, stride_width_px). Stride width may exceed config width when driver adds padding.
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
    """Apply v4l2-ctl and I2C settings. Do NOT clamp shutter to FPS."""
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
    Raw Y8 capture via v4l2-ctl. Y8: 1 byte per pixel.
    OpenCV V4L2 does not handle stride; raw buffer has stride_w x h pixels, crop to w x h.
    Returns last frame only.
    """
    frames = _capture_raw_y8_all(env, cfg, w, h, bpl, stride_w, num_frames)
    return frames[-1] if frames else None


def _read_exact(stream, n: int) -> Optional[bytes]:
    """Read exactly n bytes from stream. Returns None if EOF before n bytes."""
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def _capture_raw_y8_averaged(env, cfg, w, h, bpl, stride_w, num_frames: int) -> np.ndarray | None:
    """
    Raw Y8 capture with incremental averaging. Streams frames one-by-one to stay within memory budget.
    Returns float64 averaged frame, or None on failure.
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
    Raw Y10 capture with incremental averaging. Streams frames one-by-one to stay within memory budget.
    Returns float64 averaged frame, or None on failure.
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
    """Raw Y8 capture returning all num_frames. Returns [] on failure."""
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
    Raw Y10 capture via v4l2-ctl. V4L2 Y10: 16-bit little-endian, 10 bits per pixel.
    OpenCV cannot decode Y10; it misinterprets raw bytes as BGR, producing garbage.
    stride_w = bpl // 2 (pixels per line). Returns last frame only.
    """
    frames = _capture_raw_y10_all(env, cfg, w, h, bpl, stride_w, num_frames)
    return frames[-1] if frames else None


def _capture_raw_y10_all(env, cfg, w, h, bpl, stride_w, num_frames: int) -> list:
    """Raw Y10 capture returning all num_frames. Returns [] on failure."""
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
    Capture frame(s) from /dev/video0. Returns last frame as numpy array (GREY).
    Ensures stream is stopped, configures device. When stride != width, uses raw
    v4l2-ctl capture (OpenCV V4L2 does not handle stride correctly).
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
    Capture n consecutive frames from /dev/video0 (same config as capture_frame).
    Returns list of n frames. For n=1, equivalent to [capture_frame(1)].
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
    Capture n consecutive frames and return their average as float64.
    Uses incremental accumulation (streaming) to stay within memory budget
    when n is large (e.g. 100+). For n=1, equivalent to capture_frame().astype(float64).
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
