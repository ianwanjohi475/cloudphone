#!/usr/bin/env bash
# proxy.sh — turn the phone's proxy on/off/status quickly.
#
# Many app STORES (Aurora, Play) fail to DOWNLOAD through a residential SOCKS5
# even though browsing works. Practical workflow: install apps with the proxy
# OFF, then turn it back ON to use them.
#
#   ./scripts/proxy.sh off       # direct internet — use this to install apps
#   ./scripts/proxy.sh on        # route through your SOCKS5 again
#   ./scripts/proxy.sh status
set -uo pipefail
ADB_PORT="${ADB_PORT:-5555}"
ADDR="localhost:${ADB_PORT}"
NET="cloudphone"
MODE="${1:-status}"
adb connect "$ADDR" >/dev/null 2>&1 || true

case "$MODE" in
  off)
    adb -s "$ADDR" shell settings put global http_proxy :0 >/dev/null 2>&1
    echo "proxy OFF — phone uses direct internet (best for installing apps)"
    ;;
  on)
    IP="$(docker inspect -f '{{(index .NetworkSettings.Networks "'"$NET"'").IPAddress}}' cloudphone-proxy 2>/dev/null || true)"
    if [[ -z "$IP" ]]; then
      echo "proxy bridge not running. Start it with:"
      echo "  PROXY=\"host:port:user:pass\" ./scripts/start-phone.sh"
      exit 1
    fi
    adb -s "$ADDR" shell settings put global http_proxy "${IP}:8080" >/dev/null 2>&1
    echo "proxy ON -> ${IP}:8080 (your SOCKS5)"
    ;;
  status|*)
    cur="$(adb -s "$ADDR" shell settings get global http_proxy 2>/dev/null | tr -d '\r')"
    echo "current http_proxy = ${cur:-<none>}"
    echo "check exit IP: adb -s $ADDR shell 'curl -s https://ifconfig.me'"
    ;;
esac
