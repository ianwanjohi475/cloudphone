#!/usr/bin/env bash
# Keep the virtual webcam fed with whatever was uploaded last.
#
# The dashboard (or scripts/camera.sh) writes /data/camera/source as
#   "<kind>|<path relative to /data/camera>"     kind = image | video | pattern
# and this loop restarts ffmpeg whenever that line changes. With nothing
# uploaded the camera shows a moving test pattern, so apps never find it dead.
set -uo pipefail
DEV="${CAMERA_DEV:-/dev/video0}"
ROOT=/data/camera
CTRL="$ROOT/source"
SIZE="${CAMERA_SIZE:-1280x720}"
W="${SIZE%x*}"; H="${SIZE#*x}"
VF="scale=${W}:${H}:force_original_aspect_ratio=decrease,pad=${W}:${H}:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuyv422"
mkdir -p "$ROOT"

start_ffmpeg(){
  local kind="$1" src="$2"
  case "$kind" in
    image) [[ -f "$ROOT/$src" ]] || kind=pattern ;;
    video) [[ -f "$ROOT/$src" ]] || kind=pattern ;;
  esac
  case "$kind" in
    image) ffmpeg -nostdin -loglevel error -re -loop 1 -framerate 30 -i "$ROOT/$src" -vf "$VF" -f v4l2 "$DEV" >/dev/null 2>>"$ROOT/feed.log" & ;;
    video) ffmpeg -nostdin -loglevel error -re -stream_loop -1 -i "$ROOT/$src" -an -vf "$VF" -f v4l2 "$DEV" >/dev/null 2>>"$ROOT/feed.log" & ;;
    *)     ffmpeg -nostdin -loglevel error -re -f lavfi -i "testsrc2=size=${SIZE}:rate=30" -vf "$VF" -f v4l2 "$DEV" >/dev/null 2>>"$ROOT/feed.log" & ;;
  esac
  pid=$!
}

last=""; pid=""
while true; do
  cur="$(cat "$CTRL" 2>/dev/null || echo 'pattern|')"
  if [[ "$cur" != "$last" ]] || [[ -z "$pid" ]] || ! kill -0 "$pid" 2>/dev/null; then
    if [[ -n "$pid" ]]; then kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; fi
    start_ffmpeg "${cur%%|*}" "${cur#*|}"
    [[ "$cur" != "$last" ]] && echo "[camera] now showing: $cur"
    last="$cur"
  fi
  sleep 1
done
