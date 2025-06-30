#!/usr/bin/env bash
# Stage Google Play services (MindTheGapps) onto a phone, then trigger install.
#   ./scripts/install-gapps.sh redroid-0
#
# Notes:
#  - Match the gapps arch+android version to your REDROID_IMAGE.
#  - After install, register the device's GSF id at:
#       https://www.google.com/android/uncertified
#    or Play Store will report "Device not Play Protect certified".
set -euo pipefail
PHONE="${1:?usage: install-gapps.sh <phone-name>}"
IDX="${PHONE##*-}"
PORT=$(( ${ADB_BASE_PORT:-5555} + IDX ))
ADB="adb -s localhost:${PORT}"
GAPPS_ZIP="${GAPPS_ZIP:-downloads/MindTheGapps.zip}"

if [[ ! -f "$GAPPS_ZIP" ]]; then
  echo "Place a MindTheGapps zip at $GAPPS_ZIP (match arch + Android version)."
  echo "Source: github.com/MindTheGapps  /  androidacy MindTheGapps mirrors."
  exit 1
fi

adb connect "localhost:${PORT}" >/dev/null
$ADB root >/dev/null || true
echo "[gapps] pushing…"
$ADB shell 'mkdir -p /data/local/tmp/gapps'
$ADB push "$GAPPS_ZIP" /data/local/tmp/gapps/gapps.zip
$ADB shell 'cd /data/local/tmp/gapps && unzip -o gapps.zip >/dev/null'
# Copy system apps into the writable /system overlay redroid provides.
$ADB shell 'su -c "
  set -e
  cd /data/local/tmp/gapps
  for d in $(find . -type d -name app -o -type d -name priv-app); do
    cp -r \"$d\"/* /system/\"$(basename $d)\"/ 2>/dev/null || true
  done
  chmod -R 755 /system/app /system/priv-app 2>/dev/null || true
"' || echo "[gapps] overlay copy partial — see docs/setup.md for the manual path."

echo "[gapps] rebooting framework…"
$ADB shell 'su -c "stop && start"'
echo "[gapps] done. GSF id:"
$ADB shell "content query --uri content://com.google.android.gsf.gservices \
  --projection value --where \"name='android_id'\"" 2>/dev/null || true
echo "Register that id at https://www.google.com/android/uncertified"
