#!/usr/bin/env bash
# Diagnose whether the host can run cloudphone. Non-fatal; prints a report.
set -uo pipefail

ok()   { printf '  \033[1;32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[1;31m✗\033[0m %s\n' "$*"; FAIL=1; }
warn() { printf '  \033[1;33m!\033[0m %s\n' "$*"; }
FAIL=0

echo "cloudphone doctor"
echo "================="

echo "[docker]"
if command -v docker >/dev/null; then
  ok "docker $(docker --version | awk '{print $3}' | tr -d ,)"
  docker info >/dev/null 2>&1 && ok "docker daemon reachable" || bad "docker daemon not reachable (is it running? are you in the docker group?)"
  docker compose version >/dev/null 2>&1 && ok "docker compose v2" || bad "docker compose v2 plugin missing"
else
  bad "docker not installed"
fi

echo "[kernel modules]"
if grep -q binder /proc/filesystems 2>/dev/null || [[ -d /dev/binderfs ]] || lsmod | grep -q binder; then
  ok "binder available"
else
  bad "binder missing — run: sudo ./scripts/setup-host.sh"
fi
if lsmod | grep -q ashmem || [[ -e /dev/ashmem ]]; then
  ok "ashmem available"
else
  warn "ashmem missing — OK if kernel supports memfd (most >=5.x do)"
fi
if [[ -e /dev/video10 ]]; then
  ok "virtual camera /dev/video10 present"
else
  warn "v4l2loopback camera not present — camera virtualization off"
fi

echo "[gpu]"
if [[ -e /dev/dri/renderD128 ]]; then
  ok "/dev/dri/renderD128 present (host GPU passthrough possible)"
else
  warn "no /dev/dri render node — use REDROID_GPU_MODE=guest (software)"
fi

echo "[kvm]"
[[ -e /dev/kvm ]] && ok "/dev/kvm present" || warn "no /dev/kvm (only needed for full AVD fallback, not redroid)"

echo "[arch]"
ok "host arch: $(uname -m)"

echo
if [[ $FAIL -eq 0 ]]; then
  echo -e "\033[1;32mReady.\033[0m  Start with: make up"
else
  echo -e "\033[1;31mSome prerequisites missing — see above.\033[0m"
  exit 1
fi
