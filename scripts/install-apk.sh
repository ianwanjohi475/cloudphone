#!/usr/bin/env bash
# Install any app file onto a phone:
#   .apk, .xapk (APKPure), .apks (SAI/bundletool), .apkm (APKMirror), .zip,
#   or a folder of split APKs. OBB game data inside .xapk files is copied too.
#
#   ./scripts/install-apk.sh cloudphone-emu-0 ./game.xapk
#   ./scripts/install-apk.sh redroid-0 ./app.apk
#
# The cloudphone CLI (`cloudphone install`) does the same and also picks the
# right CPU splits and explains failures; this script needs only adb + unzip.
set -euo pipefail
PHONE="${1:?usage: install-apk.sh <phone-name> <app-file-or-dir>}"
APP="${2:?usage: install-apk.sh <phone-name> <app-file-or-dir>}"
IDX="${PHONE##*-}"
if [[ "$PHONE" == *emu-* ]]; then
  PORT=$(( ${EMULATOR_ADB_BASE_PORT:-6555} + IDX ))
else
  PORT=$(( ${ADB_BASE_PORT:-5555} + IDX ))
fi
DEV="localhost:${PORT}"
adb connect "$DEV" >/dev/null

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

DIR=""
case "${APP,,}" in
  *.apk) ;;
  *.xapk|*.apks|*.apkm|*.zip) unzip -qo "$APP" -d "$TMP"; DIR="$TMP" ;;
  *) [[ -d "$APP" ]] && DIR="$APP" || { echo "not an app file: $APP" >&2; exit 1; } ;;
esac

adb_install() {
  # -g grants runtime permissions; retry with -t for test-only builds.
  adb -s "$DEV" "$@" -r -g 2>&1 || adb -s "$DEV" "$@" -r -g -t 2>&1
}

if [[ -z "$DIR" ]]; then
  adb_install install "$APP"
else
  mapfile -t SPLITS < <(find "$DIR" -name '*.apk' -not -path '*/standalones/*' -not -path '*/standalone/*' | sort)
  [[ ${#SPLITS[@]} -gt 0 ]] || { echo "no APKs inside $APP" >&2; exit 1; }
  if [[ ${#SPLITS[@]} -eq 1 ]]; then
    adb_install install "${SPLITS[0]}"
  else
    adb_install install-multiple "${SPLITS[@]}"
  fi
  # OBB expansion files: <pkg>/main.N.<pkg>.obb under Android/obb/
  while IFS= read -r obb; do
    pkg="$(basename "$(dirname "$obb")")"
    adb -s "$DEV" shell mkdir -p "/sdcard/Android/obb/$pkg"
    adb -s "$DEV" push "$obb" "/sdcard/Android/obb/$pkg/" >/dev/null
    echo "copied game data $(basename "$obb")"
  done < <(find "$DIR" -name '*.obb')
fi
echo "Installed $(basename "$APP") on $PHONE"
