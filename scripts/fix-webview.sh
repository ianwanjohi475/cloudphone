#!/usr/bin/env bash
# fix-webview.sh — stop the "Continue with Google" / WebView login crash.
#
# Google sign-in (in Play Store, Aurora, and most apps) renders in a WebView
# whose SEPARATE sandboxed GPU process segfaults on a GPU-less container. The
# fix: force WebView to run single-process with software rendering, so there is
# no child GPU process to crash. Re-run any time a Google login screen crashes.
#
#   ./scripts/fix-webview.sh
#   ADB_PORT=5585 ./scripts/fix-webview.sh
set -uo pipefail
ADB_PORT="${ADB_PORT:-5555}"
ADDR="localhost:${ADB_PORT}"
S(){ adb -s "$ADDR" shell "$@"; }
log(){ printf '\033[1;36m[webview]\033[0m %s\n' "$*"; }

command -v adb >/dev/null || { echo "adb not found"; exit 1; }
adb connect "$ADDR" >/dev/null 2>&1 || true
adb -s "$ADDR" wait-for-device

log "forcing WebView into single-process software rendering…"
# THE key setting: no separate (crashing) WebView GPU sandbox process.
S "settings put global webview_multiprocess 0"       >/dev/null 2>&1 || true
S "settings put global webview_devtools 0"           >/dev/null 2>&1 || true

log "writing software-render flags for every Chromium surface…"
FLAGS='_ --disable-gpu --disable-gpu-compositing --disable-gpu-rasterization --disable-software-rasterizer --in-process-gpu --no-sandbox --single-process --use-gl=swiftshader --disable-features=Vulkan,WebViewZeroCopyVideo,GpuRasterization'
for f in webview-command-line android-webview-command-line chrome-command-line content-shell-command-line; do
  S "echo '$FLAGS' > /data/local/tmp/$f && chmod 644 /data/local/tmp/$f" >/dev/null 2>&1 || true
done

log "disabling hardware acceleration hints…"
S "setprop debug.hwui.renderer skiagl"   >/dev/null 2>&1 || true
S "setprop debug.egl.hw 0"               >/dev/null 2>&1 || true
S "su -c 'setprop persist.sys.force_gpu_disable 1' 2>/dev/null" >/dev/null 2>&1 || true

log "making Firefox the default browser (stable Custom-Tab / OAuth host)…"
S "cmd role add-role-holder android.app.role.BROWSER org.mozilla.fennec_fdroid" >/dev/null 2>&1 || true

log "restarting the Google/login components so they pick this up…"
for p in com.google.android.gms com.google.android.gsf com.android.vending com.aurora.store com.android.webview com.google.android.webview; do
  S "am force-stop $p" >/dev/null 2>&1 || true
done

cat <<EOF

$(log "DONE")
Now try again on the phone:
  • Aurora Store: prefer the "Anonymous" login (never hits Google's WebView).
  • If you use "Continue with Google", it now renders in-process/software and
    should not crash.
If it STILL crashes, capture the exact reason and send it to me:
  ./scripts/diagnose.sh com.google.android.gms
EOF
