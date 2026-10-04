#!/usr/bin/env bash
# Start a REAL Android phone: the official Android Emulator (Google Play image,
# Android 13) in Docker. Unlike redroid it
#   * has the real, certified Play Store, so you can sign in and install anything,
#   * runs ARM-only apps and games (built-in ARM translation),
#   * has a camera you control: any photo or video you upload is what every
#     app sees when it opens the camera.
#
#   ./scripts/start-real-phone.sh            # phone 0, adb on localhost:6555
#   IDX=1 ./scripts/start-real-phone.sh      # a second phone
#   PROXY=http://user:pass@host:port ./scripts/start-real-phone.sh
#
# Then:  ./scripts/camera.sh ./selfie.jpg     (or a video; "pattern" to reset)
#        ./scripts/install-apk.sh cloudphone-emu-0 ./game.xapk
# Needs /dev/kvm (hardware virtualization). Run sudo ./scripts/setup-host.sh once.
set -euo pipefail
cd "$(dirname "$0")/.."

log(){ printf '\033[1;36m[real-phone]\033[0m %s\n' "$*"; }
die(){ printf '\033[1;31m[real-phone]\033[0m %s\n' "$*" >&2; exit 1; }

IDX="${IDX:-0}"
NAME="cloudphone-emu-${IDX}"
PORT=$(( ${EMULATOR_ADB_BASE_PORT:-6555} + IDX ))
DATA_ROOT="$(realpath -m "${DATA_ROOT:-./data}")"
DATA="${DATA_ROOT}/emu-${IDX}"
IMAGE="${EMULATOR_IMAGE:-cloudphone/emulator:latest}"
VIDEO="/dev/video$(( ${CAMERA_VIDEO_BASE:-10} + IDX ))"
NET=cloudphone

[[ -e /dev/kvm ]] || die "/dev/kvm missing. Enable VT-x/AMD-V in the BIOS (or use a KVM-capable VPS), then retry."
[[ -r /dev/kvm && -w /dev/kvm ]] || log "note: if the phone fails to start, run: sudo usermod -aG kvm \$USER (then log in again)"

if [[ ! -e "$VIDEO" ]]; then
  log "no $VIDEO yet; loading the virtual camera module (sudo)…"
  sudo modprobe v4l2loopback devices=4 video_nr=10,11,12,13 card_label=cloudphone-cam exclusive_caps=1 \
    || log "v4l2loopback unavailable (sudo apt-get install -y v4l2loopback-dkms); the camera will be emulated, no uploads"
fi

if ! docker image inspect "$IMAGE" >/dev/null 2>&1 || [[ "${REBUILD:-}" == "1" ]]; then
  log "building $IMAGE: the first time downloads ~2 GB of Android (10-30 min)."
  log "steps [1/3] system packages, [2/3] Android tools, [3/3] Android itself; quiet stretches are normal"
  PROGRESS=()
  docker buildx version >/dev/null 2>&1 && PROGRESS=(--progress=plain)  # show every line
  docker build "${PROGRESS[@]}" -t "$IMAGE" docker/emulator
fi

docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET" >/dev/null
mkdir -p "$DATA/camera/uploads"

DEV_ARGS=(--device /dev/kvm)
[[ -e "$VIDEO" ]] && DEV_ARGS+=(--device "$VIDEO:/dev/video0")

log "starting $NAME (adb localhost:${PORT})"
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --hostname "emu-${IDX}" \
  --network "$NET" --restart unless-stopped \
  "${DEV_ARGS[@]}" \
  -p "${PORT}:5555" \
  -v "$DATA:/data" \
  -e RAM_MB="${RAM_MB:-4096}" -e CORES="${CORES:-4}" -e PROXY="${PROXY:-}" \
  --label io.cloudphone.managed=true \
  --label io.cloudphone.index="$IDX" \
  --label io.cloudphone.profile=pixel_6 \
  --label io.cloudphone.proxy="${PROXY:-}" \
  --label io.cloudphone.engine=emulator \
  --label io.cloudphone.adb="${NAME}:5555" \
  --label io.cloudphone.adbport="$PORT" \
  --label io.cloudphone.datadir="emu-${IDX}" \
  "$IMAGE" >/dev/null

log "booting Android (first boot takes a few minutes)…"
adb start-server >/dev/null 2>&1 || true
for _ in $(seq 1 180); do
  adb connect "localhost:${PORT}" >/dev/null 2>&1 || true
  if [[ "$(adb -s "localhost:${PORT}" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]]; then
    log "phone is up: adb localhost:${PORT}"
    log "camera: ./scripts/camera.sh <photo-or-video>   apps: ./scripts/install-apk.sh $NAME <file>"
    if command -v scrcpy >/dev/null; then
      exec scrcpy -s "localhost:${PORT}" --no-audio --max-size 1280 --window-title "$NAME"
    fi
    log "install scrcpy to see the screen (sudo apt-get install -y scrcpy), or use the dashboard"
    exit 0
  fi
  if [[ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" != "true" ]]; then
    docker logs --tail 40 "$NAME" >&2 || true
    die "the phone container stopped; see the log above"
  fi
  sleep 5
done
die "still booting after 15 minutes; check: docker logs $NAME"
