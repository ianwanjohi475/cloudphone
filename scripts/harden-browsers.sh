#!/usr/bin/env bash
# harden-browsers.sh — stop Chrome / WebView / Google-login from GPU-crashing.
#
# On a phone with no real GPU, Chrome and the Google sign-in WebView crash on
# their splash screen. This forces every Chromium surface down the SwiftShader
# software path and installs Firefox (the reliable browser on redroid).
# Re-run this any time a browser starts crashing.
#
#   ./scripts/harden-browsers.sh
#   ADB_PORT=5585 ./scripts/harden-browsers.sh
#   NO_FIREFOX=1 ./scripts/harden-browsers.sh   # just apply flags
set -euo pipefail

ADB_PORT="${ADB_PORT:-5555}"
ADDR="localhost:${ADB_PORT}"
DL="${DOWNLOAD_DIR:-$HOME/cloudphone-data/downloads}"
log(){ printf '\033[1;36m[harden]\033[0m %s\n' "$*"; }
S(){ adb -s "$ADDR" shell "$@"; }

command -v adb >/dev/null || { echo "adb not found"; exit 1; }
adb connect "$ADDR" >/dev/null 2>&1 || true
adb -s "$ADDR" wait-for-device

log "forcing software rendering for all Chromium surfaces…"
FLAGS='_ --use-gl=swiftshader --use-angle=swiftshader --disable-gpu --disable-gpu-compositing --disable-gpu-rasterization --disable-software-rasterizer --in-process-gpu --no-sandbox --disable-features=Vulkan,UseChromeOSDirectVideoDecoder'
for f in chrome-command-line webview-command-line content-shell-command-line android-webview-command-line; do
  S "echo '$FLAGS' > /data/local/tmp/$f && chmod 644 /data/local/tmp/$f" >/dev/null 2>&1 || true
done
S "setprop debug.hwui.renderer skiagl"  >/dev/null 2>&1 || true
S "setprop debug.egl.hw 0"              >/dev/null 2>&1 || true
S "su -c 'setprop debug.hwui.renderer skiagl' 2>/dev/null" >/dev/null 2>&1 || true

# Kill any running Chrome so it re-reads the flags next launch.
S "am force-stop com.android.chrome" >/dev/null 2>&1 || true

# Install Firefox from F-Droid (Fennec) — reliable on redroid.
if [[ "${NO_FIREFOX:-}" != "1" ]]; then
  mkdir -p "$DL"
  pkg="org.mozilla.fennec_fdroid"
  code="$(curl -fsSL "https://f-droid.org/api/v1/packages/${pkg}" 2>/dev/null \
        | python3 -c 'import sys,json; print(json.load(sys.stdin)["suggestedVersionCode"])' 2>/dev/null || true)"
  if [[ -n "$code" ]]; then
    out="$DL/firefox.apk"
    [[ -s "$out" ]] || { log "downloading Firefox…"; curl -fSL --retry 3 -o "$out" "https://f-droid.org/repo/${pkg}_${code}.apk" || true; }
    log "installing Firefox…"
    adb -s "$ADDR" install -r -g "$out" >/dev/null 2>&1 && log "Firefox installed ✓" || log "Firefox install skipped/failed"
  else
    log "couldn't resolve Firefox from F-Droid (network?). Install it from the F-Droid app."
  fi
fi

cat <<EOF

$(log "DONE")
  • Fully close Chrome from the recents view, then reopen it — it now uses
    software rendering and should not crash on the splash screen.
  • Firefox is installed and is the more reliable browser here.
  • Both use the phone's system proxy automatically (set by start-phone.sh).
EOF
