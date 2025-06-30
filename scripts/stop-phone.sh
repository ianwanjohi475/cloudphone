#!/usr/bin/env bash
# stop-phone.sh — stop/remove the phone (and proxy bridge). Data is kept.
#   ./scripts/stop-phone.sh            # stop default phone
#   PHONE=cloudphone-redroid-1 ./scripts/stop-phone.sh
#   WIPE=1 ./scripts/stop-phone.sh     # also delete its /data
set -euo pipefail
PHONE="${PHONE:-cloudphone-redroid-0}"
DATA="${DATA_ROOT:-$HOME/cloudphone-data}/${PHONE}"

docker rm -f "$PHONE" >/dev/null 2>&1 && echo "stopped $PHONE" || echo "$PHONE not running"
docker rm -f cloudphone-proxy >/dev/null 2>&1 && echo "stopped proxy bridge" || true

if [[ "${WIPE:-}" == "1" ]]; then
  rm -rf "$DATA" && echo "wiped $DATA"
fi
