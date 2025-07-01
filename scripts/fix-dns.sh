#!/usr/bin/env bash
# fix-dns.sh — give the phone a working DNS resolver.
#
# Symptom this fixes: "Unable to resolve host ... No address associated with
# hostname" (Aurora/Play/browser can't load anything with the proxy OFF).
# Redroid frequently boots with no DNS server configured.
#
#   ./scripts/fix-dns.sh
#   DNS1=1.1.1.1 DNS2=1.0.0.1 ./scripts/fix-dns.sh
set -uo pipefail
ADB_PORT="${ADB_PORT:-5555}"
ADDR="localhost:${ADB_PORT}"
DNS1="${DNS1:-8.8.8.8}"; DNS2="${DNS2:-8.8.4.4}"
S(){ adb -s "$ADDR" shell "$@"; }
log(){ printf '\033[1;36m[dns]\033[0m %s\n' "$*"; }

adb connect "$ADDR" >/dev/null 2>&1 || true
adb -s "$ADDR" wait-for-device

log "applying DNS ${DNS1} / ${DNS2}…"
S "settings put global private_dns_mode off"                               >/dev/null 2>&1 || true
S "setprop net.dns1 $DNS1; setprop net.dns2 $DNS2"                         >/dev/null 2>&1 || true
S "su -c 'setprop net.dns1 $DNS1; setprop net.dns2 $DNS2' 2>/dev/null"     >/dev/null 2>&1 || true
S "su -c 'ndc resolver setnetdns 100 localdomain $DNS1 $DNS2' 2>/dev/null" >/dev/null 2>&1 || true
S "su -c 'echo -e \"nameserver $DNS1\nnameserver $DNS2\" > /system/etc/resolv.conf' 2>/dev/null" >/dev/null 2>&1 || true

log "testing resolution…"
if S "ping -c 1 google.com" 2>/dev/null | grep -q "bytes from"; then
  log "DNS works ✓  (google.com resolves)"
else
  log "runtime DNS still not resolving — the reliable fix is a container restart"
  echo "  Restart with DNS baked in (data is preserved):"
  echo "    PHONE=<your-phone-name> ANDROID_TAG=<your-image> [PROXY=...] ./scripts/start-phone.sh"
fi
