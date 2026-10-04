#!/usr/bin/env bash
# Give WSL2 (Windows) the camera driver the real phone needs.
#
# WSL's stock kernel has no video (V4L2) support, so the v4l2loopback virtual
# camera that carries your uploaded photo/video into the phone cannot load.
# This script builds Microsoft's own WSL kernel, same version, with video
# support switched on, builds v4l2loopback for it, and tells WSL to boot it.
# It also turns on nested virtualization so /dev/kvm exists.
#
#   ./scripts/wsl-camera.sh            # ~20-40 min the first time (kernel compile)
#   then in Windows PowerShell:  wsl --shutdown   and reopen Ubuntu
#   then:  sudo ./scripts/setup-host.sh && make real-phone
#
# Undo: delete the "kernel=" line from C:\Users\<you>\.wslconfig, wsl --shutdown.
# BUILD_ONLY=1 compiles without installing anything (used for testing).
set -euo pipefail

log(){ printf '\033[1;36m[wsl-camera]\033[0m %s\n' "$*"; }
die(){ printf '\033[1;31m[wsl-camera]\033[0m %s\n' "$*" >&2; exit 1; }

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_ONLY="${BUILD_ONLY:-}"
if [[ -z "$BUILD_ONLY" ]]; then
  grep -qi microsoft /proc/version || die "this is not WSL; on normal Linux just run: sudo ./scripts/setup-host.sh"
  [[ $EUID -ne 0 ]] || die "run as your normal user (it asks for sudo when needed)"
fi

# 6.6.87.2-microsoft-standard-WSL2 -> tag linux-msft-wsl-6.6.87.2
STOCK="${WSL_KERNEL_VERSION:-$(uname -r)}"
VER="${STOCK%%-*}"
TAG="linux-msft-wsl-${VER}"
SUFFIX="-cloudphone"
V4L2LOOPBACK_REF="${V4L2LOOPBACK_REF:-v0.13.2}"
WORK="${WORK:-$HOME/.cache/cloudphone-wsl-kernel}"
SRC="$WORK/WSL2-Linux-Kernel-$VER"
mkdir -p "$WORK"

if [[ -z "$BUILD_ONLY" ]]; then
  log "installing build tools (sudo)…"
  sudo apt-get update -qq
  sudo apt-get install -y -qq build-essential flex bison libssl-dev libelf-dev bc dwarves \
    python3 git cpio kmod >/dev/null
fi

if [[ ! -d "$SRC/.git" ]]; then
  log "downloading Microsoft's WSL kernel source ($TAG)…"
  git -c advice.detachedHead=false clone -q --depth 1 --branch "$TAG" https://github.com/microsoft/WSL2-Linux-Kernel.git "$SRC" \
    || die "no kernel source tagged $TAG. Update WSL first (PowerShell: wsl --update), then retry."
fi

cd "$SRC"
log "configuring: current WSL config + video (V4L2) support…"
if [[ -r /proc/config.gz && -z "$BUILD_ONLY" ]]; then
  zcat /proc/config.gz > .config
else
  cp Microsoft/config-wsl .config
fi
# A distinct release name keeps our modules apart from WSL's stock module disk.
./scripts/config --set-str LOCALVERSION "-microsoft-standard-WSL2${SUFFIX}" \
  --module MEDIA_SUPPORT --enable MEDIA_CAMERA_SUPPORT --module VIDEO_DEV
make olddefconfig >/dev/null
grep -q '^CONFIG_VIDEO_DEV=m' .config || die "kernel config refused V4L2 (CONFIG_VIDEO_DEV); please report this"
grep -q '^CONFIG_KVM=y\|^CONFIG_KVM=m' .config || log "warning: this kernel config has no KVM"

log "compiling the kernel with $(nproc) cores (this is the long part)…"
make -j"$(nproc)" LOCALVERSION= bzImage modules >"$WORK/build.log" 2>&1 \
  || { tail -30 "$WORK/build.log"; die "kernel build failed (full log: $WORK/build.log)"; }
REL="$(make -s LOCALVERSION= kernelrelease)"
log "built kernel $REL"

LB="$WORK/v4l2loopback"
[[ -d "$LB/.git" ]] || git -c advice.detachedHead=false clone -q --depth 1 --branch "$V4L2LOOPBACK_REF" \
  https://github.com/umlaeute/v4l2loopback.git "$LB"
log "building v4l2loopback ($V4L2LOOPBACK_REF)…"
make -C "$SRC" M="$LB" LOCALVERSION= modules >"$WORK/v4l2loopback.log" 2>&1 \
  || { tail -30 "$WORK/v4l2loopback.log"; die "v4l2loopback build failed"; }

if [[ -n "$BUILD_ONLY" ]]; then
  log "BUILD_ONLY: built $SRC/arch/x86/boot/bzImage and $LB/v4l2loopback.ko for $REL"
  exit 0
fi

log "installing modules for $REL (sudo)…"
sudo make -s LOCALVERSION= modules_install >/dev/null
sudo install -D -m 644 "$LB/v4l2loopback.ko" "/lib/modules/$REL/extra/v4l2loopback.ko"
sudo depmod "$REL"

WINHOME="$(wslpath "$(cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r')")"
[[ -d "$WINHOME" ]] || die "could not find your Windows user folder"
cp arch/x86/boot/bzImage "$WINHOME/cloudphone-wsl-kernel"
WINKERNEL="$(wslpath -w "$WINHOME/cloudphone-wsl-kernel" | sed 's#\\#\\\\#g')"

CFG="$WINHOME/.wslconfig"
touch "$CFG"
[[ -f "$CFG.cloudphone-backup" ]] || cp "$CFG" "$CFG.cloudphone-backup"
python3 - "$CFG" "$WINKERNEL" <<'PY'
import re, sys
path, kernel = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8", errors="replace").read().replace("\r\n", "\n")
want = {"kernel": kernel, "nestedVirtualization": "true"}
lines = text.split("\n")
if not any(l.strip().lower() == "[wsl2]" for l in lines):
    lines = ["[wsl2]"] + ([""] if text.strip() else []) + lines
out, section = [], None
for l in lines:
    m = re.match(r"\s*\[(.+)\]\s*$", l)
    if m:
        section = m.group(1).lower()
    key = l.split("=", 1)[0].strip()
    if section == "wsl2" and "=" in l and key in want:
        continue  # replaced below
    out.append(l)
    if m and section == "wsl2":
        out += [f"{k}={v}" for k, v in want.items()]
open(path, "w", encoding="utf-8", newline="\r\n").write("\n".join(out).rstrip("\n") + "\n")
PY
log "WSL will now boot the camera-capable kernel (settings in $CFG)."
log "Next: in Windows PowerShell run  wsl --shutdown  then reopen Ubuntu and run:"
log "      cd $REPO && sudo ./scripts/setup-host.sh && make real-phone"
