#!/usr/bin/env bash
# diagnose.sh — capture WHY an app crashes, so we stop guessing.
#   ./scripts/diagnose.sh                       # defaults to Play Store
#   ./scripts/diagnose.sh com.android.chrome    # any package
#
# Clears the log, tells you to open the app, waits while it crashes, then
# prints + saves the crash reason.
set -uo pipefail
ADB_PORT="${ADB_PORT:-5555}"
ADDR="localhost:${ADB_PORT}"
PKG="${1:-com.android.vending}"
OUT="${HOME}/cloudphone-data/crash-${PKG}.log"
mkdir -p "$(dirname "$OUT")"

adb connect "$ADDR" >/dev/null 2>&1 || true
adb -s "$ADDR" wait-for-device
adb -s "$ADDR" logcat -c 2>/dev/null || true

echo "=================================================================="
echo " On the phone (scrcpy), OPEN the app now and let it crash."
echo " Package: $PKG"
echo " Capturing for 30 seconds…"
echo "=================================================================="
# Best-effort auto-launch too.
adb -s "$ADDR" shell "monkey -p $PKG -c android.intent.category.LAUNCHER 1" >/dev/null 2>&1 || true

adb -s "$ADDR" logcat -d > "$OUT.full" 2>/dev/null &
sleep 30
adb -s "$ADDR" logcat -d > "$OUT.full" 2>/dev/null || true

# Extract the interesting bits.
grep -iE "FATAL|AndroidRuntime|CRASH|$PKG|libc|signal|tombstone|beginning of crash|GmsCore|Finsky" "$OUT.full" \
  | tail -60 | tee "$OUT"

echo
echo "Full log saved: $OUT.full"
echo "Crash summary saved: $OUT"
echo "Paste the lines above to get an exact fix."
