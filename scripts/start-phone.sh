#!/usr/bin/env bash
# start-phone.sh — bring up ONE Redroid phone for native scrcpy, self-contained.
#
# Does NOT use .env or docker compose, so the stale-tag problem can't happen.
# Steps: network -> (optional) auth'd SOCKS5 proxy bridge -> redroid (correct
# tag) -> wait for boot -> anti-crash settings -> route browser via proxy ->
# print the scrcpy command.
#
# Usage:
#   ./scripts/start-phone.sh
#   PROXY="161.77.95.162:22325:14aa1d4f37e18:19efe095e4" ./scripts/start-phone.sh
#
# Override anything via env: ANDROID_TAG, ADB_PORT, PHONE, WIDTH, HEIGHT, DPI,
# DATA_ROOT, PROXY ("host:port:user:pass").
set -euo pipefail

PHONE="${PHONE:-cloudphone-redroid-0}"
TAG="${ANDROID_TAG:-redroid/redroid:13.0.0-latest}"
ADB_PORT="${ADB_PORT:-5555}"
NET="cloudphone"
W="${WIDTH:-720}"; H="${HEIGHT:-1280}"; DPI="${DPI:-320}"
DATA="${DATA_ROOT:-$HOME/cloudphone-data}/${PHONE}"
PROXY="${PROXY:-}"

log(){ printf '\033[1;36m[phone]\033[0m %s\n' "$*"; }
die(){ printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null || die "docker not found"
docker info >/dev/null 2>&1 || die "docker daemon not reachable (start Docker Desktop / dockerd)"

mkdir -p "$DATA"
docker network inspect "$NET" >/dev/null 2>&1 || { log "creating docker network '$NET'"; docker network create "$NET" >/dev/null; }

# ── 1. optional authenticated SOCKS5 -> local HTTP/SOCKS bridge (gost) ───────
PROXY_IP=""
if [[ -n "$PROXY" ]]; then
  IFS=':' read -r PH PP PU PW <<<"$PROXY"
  [[ -n "${PH:-}" && -n "${PP:-}" ]] || die "PROXY must be host:port[:user:pass]"
  log "starting proxy bridge for ${PH}:${PP} (handles SOCKS5 auth so the phone needs none)"
  docker rm -f cloudphone-proxy >/dev/null 2>&1 || true
  if [[ -n "${PU:-}" ]]; then UP="socks5://${PU}:${PW}@${PH}:${PP}"; else UP="socks5://${PH}:${PP}"; fi
  docker run -d --name cloudphone-proxy --network "$NET" --restart unless-stopped \
    ginuerzh/gost -L="http://:8080" -L="socks5://:1080" -F="$UP" >/dev/null
  sleep 2
  PROXY_IP="$(docker inspect -f "{{(index .NetworkSettings.Networks \"$NET\").IPAddress}}" cloudphone-proxy 2>/dev/null || true)"
  [[ -n "$PROXY_IP" ]] && log "proxy bridge up at ${PROXY_IP}:8080 (http) / :1080 (socks5)" \
                       || log "warning: couldn't read proxy bridge IP; will skip phone proxy config"
fi

# ── 2. redroid phone (correct tag, software GPU = crash-resistant) ───────────
log "starting $PHONE  [$TAG]"
docker rm -f "$PHONE" >/dev/null 2>&1 || true
docker run -itd --privileged --name "$PHONE" --hostname "${PHONE#cloudphone-}" \
  --network "$NET" --restart unless-stopped \
  -v "$DATA":/data \
  -p "${ADB_PORT}:5555" \
  "$TAG" \
  androidboot.redroid_width="$W" androidboot.redroid_height="$H" \
  androidboot.redroid_dpi="$DPI" androidboot.redroid_gpu_mode=guest \
  androidboot.use_memfd=1 androidboot.redroid_net_ndns=1 >/dev/null

# ── 3. adb + wait for boot ───────────────────────────────────────────────────
if ! command -v adb >/dev/null; then
  log "installing adb…"; sudo apt-get update -qq && sudo apt-get install -y -qq android-tools-adb
fi
adb start-server >/dev/null 2>&1 || true
log "waiting for Android to finish booting (first boot can take 1–3 min)…"
BOOTED=""
for _ in $(seq 1 120); do
  adb connect "localhost:${ADB_PORT}" >/dev/null 2>&1 || true
  bc="$(adb -s "localhost:${ADB_PORT}" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)"
  if [[ "$bc" == "1" ]]; then BOOTED=1; break; fi
  sleep 2
done
A=(adb -s "localhost:${ADB_PORT}" shell)
if [[ -n "$BOOTED" ]]; then log "booted ✓"; else
  log "boot not confirmed yet — it may still be coming up. Check: docker logs $PHONE"
fi

# ── 4. anti-crash settings (no root needed; redroid is debuggable) ───────────
log "applying anti-crash settings (Chrome/WebView/GL)…"
"${A[@]}" setprop debug.hwui.renderer skiagl        >/dev/null 2>&1 || true
"${A[@]}" setprop debug.stagefright.ccodec 0         >/dev/null 2>&1 || true
"${A[@]}" setprop debug.sf.nobootanimation 1         >/dev/null 2>&1 || true
FLAGS='chrome --use-gl=swiftshader --disable-gpu --in-process-gpu --no-sandbox --disable-features=Vulkan'
"${A[@]}" "echo '$FLAGS' > /data/local/tmp/chrome-command-line"   >/dev/null 2>&1 || true
"${A[@]}" "echo '$FLAGS' > /data/local/tmp/webview-command-line"  >/dev/null 2>&1 || true

# ── 5. route phone + browser through the proxy ───────────────────────────────
if [[ -n "$PROXY_IP" ]]; then
  log "routing the phone (incl. Chrome) through the proxy…"
  "${A[@]}" "settings put global http_proxy ${PROXY_IP}:8080" >/dev/null 2>&1 || true
  log "verify exit IP after opening Chrome, or run:"
  echo "    adb -s localhost:${ADB_PORT} shell 'curl -s https://ifconfig.me || true'"
fi

# ── 6. scrcpy ────────────────────────────────────────────────────────────────
echo
log "PHONE READY ✓   (native scrcpy — no web UI)"
echo
if command -v scrcpy >/dev/null; then
  echo "  Open the phone window:"
  echo "      scrcpy -s localhost:${ADB_PORT}"
else
  echo "  Install scrcpy, then open the phone window:"
  echo "      sudo apt-get install -y scrcpy"
  echo "      scrcpy -s localhost:${ADB_PORT}"
fi
echo
echo "  Install an app (APK):   adb -s localhost:${ADB_PORT} install -r yourapp.apk"
echo "  Stop the phone:         ./scripts/stop-phone.sh"
echo
echo "  (WSL2 note: scrcpy needs a GUI. Windows 11 WSLg shows it automatically;"
echo "   on Windows 10 install an X server and 'export DISPLAY=:0' first.)"
