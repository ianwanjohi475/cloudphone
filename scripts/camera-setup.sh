#!/usr/bin/env bash
# Camera virtualization / media-upload pipeline.
#
# Feeds an image, video, or a getUserMedia/RTSP stream into a phone's camera so
# apps that capture photos/video (and liveness-style flows) see synthetic media.
#
# Two layers:
#   host  : v4l2loopback creates /dev/video10; ffmpeg pumps media into it.
#   phone : redroid is started with the v4l2 node mapped to its camera HAL
#           (redroid.virtual_camera). This script wires the host side and
#           tells you the compose override to map the device.
#
#   ./scripts/camera-setup.sh image  ./face.jpg
#   ./scripts/camera-setup.sh video  ./clip.mp4
#   ./scripts/camera-setup.sh stream rtsp://host:554/cam
set -euo pipefail
MODE="${1:?usage: camera-setup.sh <image|video|stream> <source>}"
SRC="${2:?missing source}"
DEV="${CAMERA_DEV:-/dev/video10}"

command -v ffmpeg >/dev/null || { echo "ffmpeg required: sudo apt-get install -y ffmpeg"; exit 1; }
[[ -e "$DEV" ]] || { echo "$DEV missing — run: sudo ./scripts/setup-host.sh"; exit 1; }

echo "[camera] streaming $MODE '$SRC' -> $DEV (Ctrl-C to stop)"
case "$MODE" in
  image)
    exec ffmpeg -re -loop 1 -i "$SRC" -vf "format=yuv420p,scale=1280:720" \
         -f v4l2 "$DEV"
    ;;
  video)
    exec ffmpeg -re -stream_loop -1 -i "$SRC" -vf "format=yuv420p,scale=1280:720" \
         -f v4l2 "$DEV"
    ;;
  stream)
    exec ffmpeg -re -i "$SRC" -vf "format=yuv420p,scale=1280:720" -f v4l2 "$DEV"
    ;;
  *)
    echo "unknown mode: $MODE"; exit 1;;
esac
