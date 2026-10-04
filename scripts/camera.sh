#!/usr/bin/env bash
# Choose what a real phone's camera shows. Every app that opens the camera
# (front or back) sees this photo or video, looping, until you change it.
#
#   ./scripts/camera.sh ./selfie.jpg
#   ./scripts/camera.sh ./clip.mp4
#   ./scripts/camera.sh pattern            # back to the test pattern
#   IDX=1 ./scripts/camera.sh ./id.png     # phone cloudphone-emu-1
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="${1:?usage: camera.sh <photo|video|pattern>}"
IDX="${IDX:-0}"
CAM="$(realpath -m "${DATA_ROOT:-./data}")/emu-${IDX}/camera"
mkdir -p "$CAM/uploads"

if [[ "$SRC" == "pattern" ]]; then
  LINE="pattern|"
else
  [[ -f "$SRC" ]] || { echo "no such file: $SRC" >&2; exit 1; }
  case "${SRC,,}" in
    *.jpg|*.jpeg|*.png|*.webp|*.bmp|*.gif|*.tif|*.tiff) KIND=image ;;
    *.mp4|*.mov|*.m4v|*.webm|*.mkv|*.avi|*.3gp|*.mpeg|*.mpg|*.ts) KIND=video ;;
    *) echo "not a photo or video: $SRC" >&2; exit 1 ;;
  esac
  BASE="$(basename "$SRC" | tr -c 'A-Za-z0-9._-\n' '_')"
  DEST="$(date +%s%N)_${BASE}"
  cp "$SRC" "$CAM/uploads/$DEST"
  LINE="${KIND}|uploads/${DEST}"
fi
printf '%s\n' "$LINE" > "$CAM/source.tmp" && mv "$CAM/source.tmp" "$CAM/source"
echo "camera of cloudphone-emu-${IDX} now shows: ${LINE#*|}"
