#!/usr/bin/env bash
# build-image.sh — build a custom Redroid image with the REAL Google Play Store
# (GApps), ARM app translation, and optionally Magisk/Widevine baked in.
#
# Uses the community "redroid-script" (ayasa520/redroid-script), the standard
# tool for this. Heavy: downloads GApps and rebuilds the system image
# (several hundred MB, a few minutes, needs sudo + free disk).
#
#   ./scripts/build-image.sh                 # default: gapps + ndk(arm) translation
#   REDROID_SCRIPT_FLAGS="-gnm" ./scripts/build-image.sh   # + magisk
#
# Flags (combine letters after a single dash):
#   g = Google Play Store (GApps)     n = libndk ARM translation (AMD/Intel)
#   i = libhoudini ARM translation     m = Magisk root     w = Widevine DRM
set -euo pipefail

ANDROID="${ANDROID:-13.0.0}"
FLAGS="${REDROID_SCRIPT_FLAGS:--gn}"
WORK="${WORK:-$HOME/redroid-script}"
log(){ printf '\033[1;36m[build]\033[0m %s\n' "$*"; }
die(){ printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null || die "docker required"
command -v git >/dev/null || die "git required"
sudo apt-get install -y -qq lzip python3-venv >/dev/null 2>&1 || true

if [[ ! -d "$WORK/.git" ]]; then
  log "cloning redroid-script…"
  git clone https://github.com/ayasa520/redroid-script "$WORK"
else
  log "updating redroid-script…"; git -C "$WORK" pull --ff-only || true
fi
cd "$WORK"

log "setting up build env…"
python3 -m venv .venv
./.venv/bin/pip install -q -r requirements.txt

log "building redroid $ANDROID with flags '$FLAGS' (this downloads GApps; be patient)…"
sudo ./.venv/bin/python redroid.py -a "$ANDROID" $FLAGS

echo
log "DONE. Your new image(s):"
docker images --format '  {{.Repository}}:{{.Tag}}   ({{.Size}})' | grep -i redroid || true
cat <<EOF

Start a phone on the new image (replace TAG with the one above):
  ANDROID_TAG=redroid/redroid:TAG \\
  PROXY="161.77.95.162:22325:USER:PASS" ./scripts/start-phone.sh

Then on the phone (scrcpy): open "Play Store", sign in, install Chrome/Firefox.
If Play shows "Device not certified", register the device's Google id at:
  https://www.google.com/android/uncertified
Get the id with:
  adb -s localhost:\${ADB_PORT:-5555} shell 'sqlite3 /data/data/com.google.android.gsf/databases/gservices.db "select * from main where name=\"android_id\"" 2>/dev/null || content query --uri content://com.google.android.gsf.gservices --where "name=\"android_id\""'
…wait a few minutes, then clear Play Store data and reopen.
EOF
