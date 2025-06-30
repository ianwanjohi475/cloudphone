#!/usr/bin/env bash
# Install an APK (or split-apk directory) onto a phone.
#   ./scripts/install-apk.sh redroid-0 ./app.apk
set -euo pipefail
PHONE="${1:?usage: install-apk.sh <phone-name> <apk-or-dir>}"
APK="${2:?usage: install-apk.sh <phone-name> <apk-or-dir>}"
IDX="${PHONE##*-}"
PORT=$(( ${ADB_BASE_PORT:-5555} + IDX ))

adb connect "localhost:${PORT}" >/dev/null
if [[ -d "$APK" ]]; then
  mapfile -t SPLITS < <(find "$APK" -maxdepth 1 -name '*.apk' | sort)
  adb -s "localhost:${PORT}" install-multiple -r "${SPLITS[@]}"
else
  adb -s "localhost:${PORT}" install -r "$APK"
fi
echo "Installed $APK on $PHONE"
