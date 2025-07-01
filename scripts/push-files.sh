#!/usr/bin/env bash
# push-files.sh — upload a folder from your PC into the phone.
#   * .apk files  -> installed as apps
#   * everything else -> copied to /sdcard/Download and made visible in Gallery/Files
#
# Windows paths work directly (auto-converted to WSL /mnt/... form):
#   ./scripts/push-files.sh 'C:\Users\ADMIN\Downloads\cloud'
#   ./scripts/push-files.sh ~/stuff            # a Linux path also works
#   ADB_PORT=5585 ./scripts/push-files.sh 'C:\Users\ADMIN\Downloads\cloud'
set -euo pipefail

ADB_PORT="${ADB_PORT:-5555}"
ADDR="localhost:${ADB_PORT}"
SRC_RAW="${1:?usage: push-files.sh <folder>   e.g. 'C:\\Users\\ADMIN\\Downloads\\cloud'}"
DEST="${DEST:-/sdcard/Download}"

log(){ printf '\033[1;36m[push]\033[0m %s\n' "$*"; }
die(){ printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

# Convert a Windows path (C:\Users\..) to WSL (/mnt/c/Users/..).
win_to_wsl(){
  local p="$1"
  if [[ "$p" =~ ^[A-Za-z]:\\ || "$p" =~ ^[A-Za-z]:/ ]]; then
    local drive="${p:0:1}"; drive="${drive,,}"
    p="/mnt/${drive}/${p:3}"
    p="${p//\\//}"
  fi
  echo "$p"
}
SRC="$(win_to_wsl "$SRC_RAW")"
[[ -d "$SRC" ]] || die "folder not found: $SRC  (from '$SRC_RAW')"

command -v adb >/dev/null || die "adb not found"
adb connect "$ADDR" >/dev/null 2>&1 || true
adb -s "$ADDR" wait-for-device
adb -s "$ADDR" shell "mkdir -p $DEST" >/dev/null 2>&1 || true

apks=0 files=0
shopt -s nullglob dotglob
while IFS= read -r -d '' f; do
  base="$(basename "$f")"
  if [[ "${base,,}" == *.apk ]]; then
    log "installing app: $base"
    if adb -s "$ADDR" install -r -g "$f" >/dev/null 2>&1 || adb -s "$ADDR" install -r "$f" >/dev/null 2>&1; then
      log "  installed ✓"; apks=$((apks+1))
    else
      log "  install failed (ABI mismatch? try the gapps+ndk image)"
    fi
  else
    log "uploading file: $base"
    adb -s "$ADDR" push "$f" "$DEST/$base" >/dev/null 2>&1 && files=$((files+1)) || log "  push failed: $base"
  fi
done < <(find "$SRC" -maxdepth 1 -type f -print0)

# Make pushed media show up in Gallery/Files immediately.
adb -s "$ADDR" shell "am broadcast -a android.intent.action.MEDIA_MOUNTED -d file://$DEST" >/dev/null 2>&1 || true

log "done — installed $apks app(s), uploaded $files file(s) to $DEST"
echo "  On the phone: open Files or Gallery to see them (folder: Download)."
