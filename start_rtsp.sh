#!/bin/bash

ENV_CONFIG="${ENV_CONFIG:-/home/raspberry/env_config.json}"
if [ -f "$ENV_CONFIG" ]; then
  _env=$(cat "$ENV_CONFIG")
  CONFIG=$(echo "$_env" | jq -r '.paths.camera_config')
  DEVICE=$(echo "$_env" | jq -r '.device.video')
  RTSP_URL=$(echo "$_env" | jq -r '.rtsp.url')
  I2C_TOOL=$(echo "$_env" | jq -r '.paths.i2c_tool')
  I2C_BUS=$(echo "$_env" | jq -r '.device.i2c_bus')
else
  CONFIG="/home/raspberry/camera_config.json"
  DEVICE="/dev/video0"
  RTSP_URL="rtsp://10.0.0.114:8554/mystream"
  I2C_TOOL="/home/raspberry/raspberrypi_v4l2/mv_tools_rpi/mv_mipi_i2c_new.sh"
  I2C_BUS=10
fi

if [ ! -f "$CONFIG" ]; then
  echo "Camera config file not found: $CONFIG" >&2
  exit 1
fi

cfg=$(cat "$CONFIG")

RES=$(echo "$cfg" | jq -r .resolution)
FPS=$(echo "$cfg" | jq .fps)
SHUTTER=$(echo "$cfg" | jq .shutter)
GAIN=$(echo "$cfg" | jq .gain)
# Encoder: libx264 (works on Pi Zero 2W; use h264_v4l2m2m on Pi 4/5 for hardware)
H264_CODEC="libx264"
# Pixel format: Y8 (GREY), Y10, or Y10P. Default Y8.
PIXEL_FORMAT=$(echo "$cfg" | jq -r '.pixel_format // "Y8"')
PIXEL_FORMAT=${PIXEL_FORMAT:-Y8}

WIDTH=$(echo "$RES" | cut -d"x" -f1)
HEIGHT=$(echo "$RES" | cut -d"x" -f2)

if [ -z "$WIDTH" ] || [ -z "$HEIGHT" ]; then
  echo "Invalid resolution in config: $RES" >&2
  exit 1
fi

if [ -z "$FPS" ] || [ "$FPS" -le 0 ]; then
  echo "Invalid fps in config: $FPS" >&2
  exit 1
fi

# Clamp shutter to sensor limits for given fps (max 1e6 / fps microseconds)
if [ -n "$SHUTTER" ] && [ "$SHUTTER" -gt 0 ] 2>/dev/null; then
  MAX_EXPOSURE=$((1000000 / FPS))
  if [ "$SHUTTER" -gt "$MAX_EXPOSURE" ]; then
    echo "Requested shutter ${SHUTTER}us exceeds max ${MAX_EXPOSURE}us at ${FPS}fps, clamping."
    SHUTTER=$MAX_EXPOSURE
  fi
fi

# V4L2 fourcc: GREY (Y8), 'Y10 ' (10-bit unpacked), Y10P (10-bit packed)
case "$PIXEL_FORMAT" in
  Y8|GREY|grey)   V4L2_FMT="GREY"; FFMPEG_IN_FMT="gray";;
  Y10)            V4L2_FMT="Y10 "; FFMPEG_IN_FMT="gray10le";;
  Y10P)           V4L2_FMT="Y10P"; FFMPEG_IN_FMT="y10p";;
  *)
    echo "Unsupported pixel_format in config: $PIXEL_FORMAT (use Y8, Y10, or Y10P)" >&2
    exit 1
    ;;
esac

echo "Using MV camera on $DEVICE with ${WIDTH}x${HEIGHT} @ ${FPS}fps, format $PIXEL_FORMAT"

if ! command -v v4l2-ctl >/dev/null 2>&1; then
  echo "v4l2-ctl not found, cannot configure camera" >&2
  exit 1
fi

v4l2-ctl -d "$DEVICE" --set-ctrl roi_x=0
v4l2-ctl -d "$DEVICE" --set-ctrl roi_y=0
v4l2-ctl -d "$DEVICE" --set-fmt-video=width="$WIDTH",height="$HEIGHT",pixelformat="$V4L2_FMT"
v4l2-ctl -d "$DEVICE" --set-ctrl frame_rate="$FPS"

# Apply exposure and gain via VEYE I2C tool when available
if [ -x "$I2C_TOOL" ]; then
  echo "Applying exposure/gain via $I2C_TOOL on bus $I2C_BUS"
  "$I2C_TOOL" -w expmode 0 -b "$I2C_BUS" >/dev/null 2>&1
  "$I2C_TOOL" -w gainmode 0 -b "$I2C_BUS" >/dev/null 2>&1

  if [ -n "$SHUTTER" ] && [ "$SHUTTER" -gt 0 ] 2>/dev/null; then
    "$I2C_TOOL" -w metime "$SHUTTER" -b "$I2C_BUS" >/dev/null 2>&1
  fi

  if [ -n "$GAIN" ]; then
    "$I2C_TOOL" -w mgain "$GAIN" -b "$I2C_BUS" >/dev/null 2>&1
  fi
else
  echo "I2C_TOOL $I2C_TOOL not found or not executable, skipping exposure/gain apply"
fi

BPL=$(v4l2-ctl -d "$DEVICE" --get-fmt-video | grep 'Bytes per Line' | awk '{print $NF}')
case "$PIXEL_FORMAT" in
  Y8|GREY|grey)   STRIDE_W=$BPL;;
  Y10)            STRIDE_W=$((BPL / 2));;
  Y10P)           STRIDE_W=$((BPL * 4 / 5));;
esac

echo "Driver reports bytesperline=$BPL, stride_width=${STRIDE_W}px (image width=${WIDTH}px)"

if [ "$STRIDE_W" -ne "$WIDTH" ]; then
  echo "Stride padding detected — using raw pipe with crop"
  v4l2-ctl -d "$DEVICE" --stream-mmap --stream-to=- | \
  ffmpeg -f rawvideo -pixel_format "$FFMPEG_IN_FMT" -video_size "${STRIDE_W}x${HEIGHT}" -framerate "$FPS" -i - \
    -vf "crop=${WIDTH}:${HEIGHT}:0:0,format=yuv420p" \
    -c:v "$H264_CODEC" -preset ultrafast -tune zerolatency -b:v 1M -maxrate 1M -bufsize 2M \
    -f rtsp "$RTSP_URL"
else
  ffmpeg -f v4l2 -framerate "$FPS" -video_size "${WIDTH}x${HEIGHT}" -input_format "$FFMPEG_IN_FMT" -i "$DEVICE" \
    -vf "format=yuv420p" \
    -c:v "$H264_CODEC" -preset ultrafast -tune zerolatency -b:v 1M -maxrate 1M -bufsize 2M \
    -f rtsp "$RTSP_URL"
fi
