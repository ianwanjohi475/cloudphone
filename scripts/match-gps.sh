#!/usr/bin/env bash
# match-gps.sh — set the phone's GPS to match its PROXY exit location.
#
# Routing through the proxy already gives websites/browser your proxy's IP
# location. This also moves the phone's *GPS* to the same city, so Maps and
# location-aware apps agree with the IP. Run it AFTER the phone is up on the
# proxy (proxy ON).
#
#   ./scripts/match-gps.sh
#   LAT=40.71 LON=-74.00 ./scripts/match-gps.sh    # or set coords manually
set -uo pipefail
ADB_PORT="${ADB_PORT:-5555}"
ADDR="localhost:${ADB_PORT}"
S(){ adb -s "$ADDR" shell "$@"; }
log(){ printf '\033[1;36m[gps]\033[0m %s\n' "$*"; }

adb connect "$ADDR" >/dev/null 2>&1 || true
adb -s "$ADDR" wait-for-device

LAT="${LAT:-}"; LON="${LON:-}"; CITY=""
if [[ -z "$LAT" || -z "$LON" ]]; then
  log "asking the phone for its proxy exit location (via ip-api)…"
  JSON="$(S 'curl -s --max-time 20 http://ip-api.com/json 2>/dev/null' || true)"
  LAT="$(echo "$JSON" | grep -o '\"lat\":[-0-9.]*' | head -1 | cut -d: -f2)"
  LON="$(echo "$JSON" | grep -o '\"lon\":[-0-9.]*' | head -1 | cut -d: -f2)"
  CITY="$(echo "$JSON" | grep -o '\"city\":\"[^\"]*\"' | head -1 | cut -d: -f2 | tr -d '\"')"
fi
if [[ -z "$LAT" || -z "$LON" ]]; then
  log "couldn't auto-detect location (proxy off? no curl?). Set it manually:"
  echo "  LAT=<lat> LON=<lon> ./scripts/match-gps.sh"
  exit 1
fi
log "target location: ${LAT}, ${LON} ${CITY:+($CITY)}"

# Enable mock location (developer setting) and register a shell test provider.
S "settings put secure mock_location 1"                    >/dev/null 2>&1 || true
S "settings put global development_settings_enabled 1"     >/dev/null 2>&1 || true
S "appops set com.android.shell android:mock_location allow" >/dev/null 2>&1 || true

set_provider(){ # provider
  local p="$1"
  S "cmd location providers add-test-provider $p --requiresNetwork false --requiresSatellite false --requiresCell false --hasMonetaryCost false --supportsAltitude true --supportsSpeed true --supportsBearing true --powerRequirement 1" >/dev/null 2>&1 || true
  S "cmd location providers set-test-provider-enabled $p true" >/dev/null 2>&1 || true
  S "cmd location providers set-test-provider-location $p --location ${LAT},${LON} --accuracy 5 --altitude 12" >/dev/null 2>&1 || true
}
for p in gps network fused; do set_provider "$p"; done

# Root fallback (gapps image ships Magisk).
S "su -c 'cmd location providers set-test-provider-location gps --location ${LAT},${LON} --accuracy 5' 2>/dev/null" >/dev/null 2>&1 || true

# Set locale/timezone hint toward the location's country if we got a city.
log "GPS set to ${LAT}, ${LON}."
echo "  Verify on the phone: open Google Maps → 'my location' should be near ${CITY:-the proxy city}."
echo "  If Maps ignores it, install a mock-GPS app and set it as the mock provider,"
echo "  or use the gapps+magisk image where the root path applies it directly."
