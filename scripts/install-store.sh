#!/usr/bin/env bash
# install-store.sh — put an app store + browsers on the phone, the reliable way.
#
# Installs:
#   1. F-Droid       (open-source store; universal APK, always works)
#   2. Aurora Store  (open-source Google Play CLIENT — installs the *real*
#                     Chrome / Firefox from Google with an anonymous account,
#                     no GApps and no Google sign-in required)
# Then applies the Chrome/WebView anti-crash flags so Chromium browsers don't
# die on a GPU that isn't there.
#
# After it runs: open Aurora Store on the phone (via scrcpy), let it log in
# anonymously, search "Chrome" / "Firefox", install. They'll run.
#
#   ./scripts/install-store.sh            # default phone on localhost:5555
#   ADB_PORT=5585 ./scripts/install-store.sh
set -euo pipefail

ADB_PORT="${ADB_PORT:-5555}"
DL="${DOWNLOAD_DIR:-$HOME/cloudphone-data/downloads}"
ADDR="localhost:${ADB_PORT}"
log(){ printf '\033[1;36m[store]\033[0m %s\n' "$*"; }
die(){ printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

command -v adb >/dev/null || die "adb not found"
command -v curl >/dev/null || die "curl not found (sudo apt-get install -y curl)"
mkdir -p "$DL"
adb connect "$ADDR" >/dev/null 2>&1 || true
adb -s "$ADDR" wait-for-device

install_apk(){ # url, name
  local url="$1" name="$2" out="$DL/$2.apk"
  if [[ ! -s "$out" ]]; then
    log "downloading $name…"
    curl -fSL --retry 3 -o "$out" "$url" || { log "download failed for $name ($url)"; return 1; }
  fi
  log "installing $name…"
  adb -s "$ADDR" install -r -g "$out" >/dev/null 2>&1 \
    && log "$name installed ✓" \
    || { adb -s "$ADDR" install -r "$out" >/dev/null 2>&1 && log "$name installed ✓" || log "$name install failed"; }
}

# 1. F-Droid (stable, universal) -------------------------------------------------
install_apk "https://f-droid.org/F-Droid.apk" "FDroid" || true

# 2. Aurora Store — resolve latest APK from the GitLab release API ---------------
log "resolving latest Aurora Store…"
AURORA_URL="$(curl -fsSL "https://gitlab.com/api/v4/projects/AuroraOSS%2FAuroraStore/releases" 2>/dev/null \
  | python3 -c 'import sys,json
try:
    rels=json.load(sys.stdin)
    for a in rels[0]["assets"]["links"]:
        if a["url"].endswith(".apk"): print(a["url"]); break
except Exception: pass' || true)"
if [[ -n "$AURORA_URL" ]]; then
  install_apk "$AURORA_URL" "AuroraStore" || true
else
  log "couldn't auto-resolve Aurora — install it from inside F-Droid instead"
  log "(F-Droid → search 'Aurora Store' → Install)"
fi

# 3. Anti-crash flags for Chromium browsers -------------------------------------
log "applying Chrome/WebView anti-crash flags…"
FLAGS='chrome --use-gl=swiftshader --disable-gpu --in-process-gpu --no-sandbox --disable-features=Vulkan'
for f in chrome-command-line webview-command-line; do
  adb -s "$ADDR" shell "echo '$FLAGS' > /data/local/tmp/$f" >/dev/null 2>&1 || true
done

cat <<EOF

$(log "DONE")
On the phone (scrcpy window):
  1. Open "Aurora Store"  → Anonymous login (no Google account needed)
  2. Search "Chrome"   → Install
  3. Search "Firefox"  → Install
  4. Open them — they're configured not to GPU-crash.

If a browser refuses to install with "not compatible / ABI", your image is
x86-only and that build is ARM-only. Build an ARM-capable image:
  ./scripts/build-image.sh        # adds ndk translation (+ optional Play Store)

Prefer pure F-Droid browsers (no Google at all)? In F-Droid install
"Fennec" (Firefox) and "Cromite" (Chromium) instead.
EOF
