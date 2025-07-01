#!/usr/bin/env bash
# install-store.sh — put a working app store + browsers on the phone.
#
# Redroid has no Play Store. This installs (all straight from F-Droid's official
# API, no Google account needed):
#   - F-Droid       open-source store
#   - Aurora Store  an open-source Google Play CLIENT — installs the *real*
#                   Chrome and any Play app anonymously (this is your "Play Store")
#   - Firefox       (Fennec) directly, works immediately
# Then applies the Chrome/WebView anti-crash flags.
#
#   ./scripts/install-store.sh
#   ADB_PORT=5585 ./scripts/install-store.sh
#   APPS="com.aurora.store org.mozilla.fennec_fdroid org.videolan.vlc" ./scripts/install-store.sh
set -euo pipefail

ADB_PORT="${ADB_PORT:-5555}"
ADDR="localhost:${ADB_PORT}"
DL="${DOWNLOAD_DIR:-$HOME/cloudphone-data/downloads}"
# Default set: F-Droid store client, Aurora (Play client), Firefox.
APPS="${APPS:-org.fdroid.fdroid com.aurora.store org.mozilla.fennec_fdroid}"

log(){ printf '\033[1;36m[store]\033[0m %s\n' "$*"; }
die(){ printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

command -v adb  >/dev/null || die "adb not found"
command -v curl >/dev/null || die "curl not found (sudo apt-get install -y curl)"
mkdir -p "$DL"
adb connect "$ADDR" >/dev/null 2>&1 || true
adb -s "$ADDR" wait-for-device

# Resolve the latest APK URL for an F-Droid package via the official API.
fdroid_url(){ # package -> prints https URL or nothing
  local pkg="$1" code
  code="$(curl -fsSL "https://f-droid.org/api/v1/packages/${pkg}" 2>/dev/null \
        | python3 -c 'import sys,json; print(json.load(sys.stdin)["suggestedVersionCode"])' 2>/dev/null || true)"
  [[ -n "$code" ]] && echo "https://f-droid.org/repo/${pkg}_${code}.apk"
}

fdroid_install(){ # package
  local pkg="$1" url out="$DL/$1.apk"
  url="$(fdroid_url "$pkg")"
  [[ -z "$url" ]] && { log "could not resolve $pkg on F-Droid — skipping"; return 1; }
  if [[ ! -s "$out" ]]; then
    log "downloading $pkg…"
    curl -fSL --retry 3 -o "$out" "$url" || { log "download failed: $pkg"; return 1; }
  fi
  log "installing $pkg…"
  if adb -s "$ADDR" install -r -g "$out" >/dev/null 2>&1 || adb -s "$ADDR" install -r "$out" >/dev/null 2>&1; then
    log "$pkg installed ✓"
  else
    log "$pkg install failed (ABI mismatch? see build-image.sh for ARM support)"
  fi
}

for pkg in $APPS; do fdroid_install "$pkg" || true; done

# Chrome/WebView anti-crash flags (so Chromium browsers don't die on software GL).
log "applying Chrome/WebView anti-crash flags…"
FLAGS='chrome --use-gl=swiftshader --disable-gpu --in-process-gpu --no-sandbox --disable-features=Vulkan'
for f in chrome-command-line webview-command-line; do
  adb -s "$ADDR" shell "echo '$FLAGS' > /data/local/tmp/$f" >/dev/null 2>&1 || true
done

cat <<EOF

$(log "DONE — installed apps:")
$(adb -s "$ADDR" shell pm list packages -3 2>/dev/null | sed 's/package:/  - /')

Now, on the phone (scrcpy window):
  • Firefox is ready — just open it.
  • For CHROME / any Play Store app: open "Aurora Store" → Anonymous login
    (no Google account) → search "Chrome" → Install. It pulls the real app
    from Google's servers. Anti-crash flags are already set, so it won't crash.

Want a different app? Pass its package id:
  APPS="com.aurora.store" ./scripts/install-store.sh
EOF
