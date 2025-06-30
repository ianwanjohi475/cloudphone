#!/usr/bin/env bash
# Load the Linux kernel modules Redroid needs on the host (Ubuntu).
# Idempotent. Run once per boot, or install the systemd drop-in it offers.
set -euo pipefail

log()  { printf '\033[1;36m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn ]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run with sudo: sudo $0"

KREL="$(uname -r)"
log "Kernel: $KREL"

# 1. binder ------------------------------------------------------------------
if modprobe binder_linux devices="binder,hwbinder,vndbinder" 2>/dev/null; then
  log "binder_linux loaded (binder,hwbinder,vndbinder)."
elif [[ -d /dev/binderfs ]] || grep -q binder /proc/filesystems 2>/dev/null; then
  log "binderfs already present."
else
  warn "binder_linux not available as a module."
  warn "Install it:  sudo apt-get install -y linux-modules-extra-$KREL"
  warn "or use the anbox/binder DKMS module. See docs/setup.md."
fi

# Mount binderfs if the kernel uses it (Android 11+/redroid 12+).
if grep -q binder /proc/filesystems 2>/dev/null && [[ ! -d /dev/binderfs ]]; then
  mkdir -p /dev/binderfs
  mount -t binder binder /dev/binderfs 2>/dev/null && log "binderfs mounted." || true
fi

# 2. ashmem (older kernels; newer redroid uses memfd instead) ----------------
if modprobe ashmem_linux 2>/dev/null; then
  log "ashmem_linux loaded."
else
  warn "ashmem_linux not loadable — fine on kernels with memfd (use_memfd=1)."
fi

# 3. v4l2loopback (virtual camera for getUserMedia / media-upload pipeline) ---
if modprobe v4l2loopback devices=1 video_nr=10 card_label="cloudphone-cam" exclusive_caps=1 2>/dev/null; then
  log "v4l2loopback ready at /dev/video10 (virtual camera)."
else
  warn "v4l2loopback not loaded — camera virtualization disabled."
  warn "Install:  sudo apt-get install -y v4l2loopback-dkms"
fi

# 4. Persist across reboots ---------------------------------------------------
MODCONF=/etc/modules-load.d/cloudphone.conf
cat > "$MODCONF" <<'EOF'
binder_linux
ashmem_linux
v4l2loopback
EOF
echo 'options binder_linux devices=binder,hwbinder,vndbinder' > /etc/modprobe.d/cloudphone-binder.conf
echo 'options v4l2loopback devices=1 video_nr=10 card_label=cloudphone-cam exclusive_caps=1' > /etc/modprobe.d/cloudphone-v4l2.conf
log "Persisted module config to $MODCONF"

log "Host setup complete. Verify with: ./scripts/doctor.sh"
