#!/usr/bin/env bash
# Boot the emulator headless, feed the virtual webcam, expose adb on :5555.
#
# Env:
#   DEVICE     hardware profile for avdmanager (default pixel_6)
#   RAM_MB     guest RAM (default 4096)    CORES  guest vCPUs (default 4)
#   DISK       data partition size (default 16G)
#   WIDTH/HEIGHT/DPI  screen (default 1080x2400 @ 420)
#   GPU        emulator -gpu mode (default swiftshader_indirect; "host" needs /dev/dri)
#   CAMERA_DEV v4l2 device fed by camera-feed.sh (default /dev/video0)
#   PROXY      http://[user:pass@]host:port routed for the whole phone (optional)
set -euo pipefail

log(){ printf '[emulator] %s\n' "$*"; }

[[ -e /dev/kvm ]] || { log "ERROR: /dev/kvm missing. Run the container with --device /dev/kvm (and enable virtualization in BIOS)."; exit 1; }

export ANDROID_AVD_HOME=/data/avd
export ANDROID_EMULATOR_HOME=/data/.android
mkdir -p "$ANDROID_AVD_HOME" "$ANDROID_EMULATOR_HOME" /data/camera/uploads

AVD=phone
SYSIMG="system-images;android-${API};${IMAGE_TAG};${ABI}"
if [[ ! -f "$ANDROID_AVD_HOME/${AVD}.ini" ]]; then
  log "creating the phone (first start only)…"
  echo no | avdmanager create avd -n "$AVD" -k "$SYSIMG" -d "${DEVICE:-pixel_6}" -p "$ANDROID_AVD_HOME/${AVD}.avd" >/dev/null
fi
CFG="$ANDROID_AVD_HOME/${AVD}.avd/config.ini"
setcfg(){ grep -q "^$1=" "$CFG" && sed -i "s#^$1=.*#$1=$2#" "$CFG" || echo "$1=$2" >> "$CFG"; }
setcfg hw.ramSize "${RAM_MB:-4096}"
setcfg hw.cpu.ncore "${CORES:-4}"
setcfg disk.dataPartition.size "${DISK:-16G}"
setcfg hw.lcd.width "${WIDTH:-1080}"
setcfg hw.lcd.height "${HEIGHT:-2400}"
setcfg hw.lcd.density "${DPI:-420}"
setcfg hw.keyboard yes
setcfg hw.gpu.enabled yes
setcfg hw.gpu.mode "${GPU:-swiftshader_indirect}"
setcfg PlayStore.enabled true
setcfg hw.audioInput no
setcfg hw.audioOutput no

# Camera: start the feeder first. With v4l2loopback exclusive_caps=1 the device
# only shows up as a webcam once something is writing to it.
CAM=emulated
DEV="${CAMERA_DEV:-/dev/video0}"
if [[ -e "$DEV" ]]; then
  CAMERA_DEV="$DEV" /usr/local/bin/camera-feed.sh &
  for _ in $(seq 1 20); do
    v4l2-ctl -d "$DEV" --all 2>/dev/null | grep -q "Video Capture" && break
    sleep 0.5
  done
  if emulator -webcam-list 2>/dev/null | grep -q webcam0; then
    CAM=webcam0
    log "camera: uploaded media feed on $DEV (webcam0)"
  else
    log "camera: $DEV present but the emulator does not list it; using the emulated camera"
  fi
else
  log "camera: no $DEV mapped; using the emulated camera (map /dev/video10 for photo/video upload)"
fi
setcfg hw.camera.back "$CAM"
setcfg hw.camera.front "$CAM"

# Expose adb: the emulator only listens on 127.0.0.1:5557 (console 5556).
socat TCP-LISTEN:5555,fork,reuseaddr TCP:127.0.0.1:5557 &

adb start-server >/dev/null 2>&1 || true
(
  adb -s emulator-5556 wait-for-device
  until [[ "$(adb -s emulator-5556 shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]]; do sleep 2; done
  adb -s emulator-5556 shell settings put global window_animation_scale 0.5 >/dev/null 2>&1 || true
  adb -s emulator-5556 shell settings put global transition_animation_scale 0.5 >/dev/null 2>&1 || true
  adb -s emulator-5556 shell settings put secure show_ime_with_hard_keyboard 1 >/dev/null 2>&1 || true
  log "BOOTED. adb is on port 5555 of this container."
) &

EXTRA=()
if [[ -n "${PROXY:-}" ]]; then
  if [[ "$PROXY" == http://* ]]; then
    EXTRA+=(-http-proxy "$PROXY")
    log "network: all traffic through $(sed -E 's#//[^@]*@#//***@#' <<<"$PROXY")"
  else
    log "network: PROXY must be http://… for the emulator; ignoring it"
  fi
fi

log "starting Android ${API} (${IMAGE_TAG}, ${ABI})…"
exec emulator -avd "$AVD" -port 5556 \
  -no-window -no-audio -no-boot-anim -no-snapshot-save \
  -gpu "${GPU:-swiftshader_indirect}" -accel on \
  -camera-back "$CAM" -camera-front "$CAM" \
  -netdelay none -netspeed full \
  "${EXTRA[@]}" ${EMULATOR_ARGS:-}
