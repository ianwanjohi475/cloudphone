#!/usr/bin/env bash
# Root a Redroid phone with Magisk so resetprop / iptables / mock-location work.
#
# Redroid images do NOT ship Magisk. The reliable path is to patch the ramdisk,
# but for a container the simplest working approach is the "magisk-on-redroid"
# overlay: push the magisk binaries into /data and start magiskd, then install
# the Magisk app. This script automates that overlay.
#
#   ./scripts/magisk-setup.sh redroid-0 [magisk.zip]
set -euo pipefail
PHONE="${1:?usage: magisk-setup.sh <phone-name> [magisk.zip]}"
ZIP="${2:-downloads/Magisk.zip}"
IDX="${PHONE##*-}"
PORT=$(( ${ADB_BASE_PORT:-5555} + IDX ))
ADB="adb -s localhost:${PORT}"

if [[ ! -f "$ZIP" ]]; then
  echo "Magisk zip not found at $ZIP."
  echo "Download the latest Magisk-vXX.X.apk from github.com/topjohnwu/Magisk,"
  echo "rename to Magisk.zip, and place it in ./downloads/. Then re-run."
  exit 1
fi

adb connect "localhost:${PORT}" >/dev/null
$ADB root >/dev/null || true
$ADB wait-for-device

echo "[magisk] pushing overlay…"
$ADB push "$ZIP" /data/local/tmp/magisk.zip
$ADB shell 'cd /data/local/tmp && unzip -o magisk.zip -d magisk >/dev/null'
# Stage the magisk binaries and launch the daemon (best-effort; arch-dependent).
$ADB shell 'su -c "mkdir -p /data/adb/magisk && cp /data/local/tmp/magisk/lib/*/* /data/adb/magisk/ 2>/dev/null; chmod -R 755 /data/adb/magisk"' || true
$ADB shell 'su -c "/data/adb/magisk/magisk --daemon"' 2>/dev/null || true

# Install the Magisk manager app for UI + module management.
$ADB install -r "$ZIP" 2>/dev/null || \
  echo "[magisk] couldn't auto-install the app — install Magisk.apk manually."

echo "[magisk] verifying resetprop…"
if $ADB shell 'command -v resetprop' >/dev/null 2>&1; then
  echo "[magisk] OK — resetprop available on $PHONE"
else
  echo "[magisk] resetprop not yet on PATH; reboot the phone and re-check."
  echo "         cloudphone restart $PHONE"
fi
