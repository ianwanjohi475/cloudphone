#!/usr/bin/env bash
# Start a shared adb server, connect to every phone listed in AUTO_CONNECT,
# then launch ws-scrcpy. New phones created by the CLI are connected the same
# way via `adb connect`, so they appear in the device list automatically.
set -euo pipefail

adb start-server

connect_loop() {
  # Keep (re)connecting in the background so phones that boot late, restart,
  # or get added by the orchestrator show up without a manual refresh.
  while true; do
    IFS=',' read -ra TARGETS <<< "${AUTO_CONNECT:-}"
    for t in "${TARGETS[@]}"; do
      t="$(echo "$t" | xargs)"   # trim
      [[ -z "$t" ]] && continue
      adb connect "$t" >/dev/null 2>&1 || true
    done
    # Phones created later by the dashboard/CLI: Docker DNS resolves their
    # container names, so probe the first few of each kind.
    for i in $(seq 0 "${SCAN_MAX:-9}"); do
      for h in "cloudphone-emu-$i" "cloudphone-redroid-$i"; do
        getent hosts "$h" >/dev/null 2>&1 && adb connect "$h:5555" >/dev/null 2>&1
      done
    done
    sleep 15
  done
}
connect_loop &

echo "[ws-scrcpy] starting on :8000 (auto-connect: ${AUTO_CONNECT:-none})"
exec node index.js
