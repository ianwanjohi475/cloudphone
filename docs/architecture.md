# Architecture

## Components

- **Redroid containers** — each phone is one privileged `redroid/redroid`
  container running a full Android userspace on the host kernel. State lives in
  a per-phone bind mount (`data/redroid-N`), so phones survive recreation.
- **ws-scrcpy** — Node service that speaks adb to every phone and streams the
  screen + input to the browser over WebSocket. It auto-`adb connect`s phones
  listed in `AUTO_CONNECT` and re-scans every 15s, so new phones appear without
  a refresh.
- **Orchestrator** (`orchestrator/cloudphone`) — Python package that owns phone
  lifecycle via the Docker SDK and post-boot provisioning via adb. Exposes both
  a CLI (`cloudphone …`) and a FastAPI dashboard; both call the same
  `PhoneManager`.
- **Dashboard** — static HTML/JS served by FastAPI; lists phones, shows health,
  triggers lifecycle actions, and embeds the ws-scrcpy viewer per phone.

## Host kernel surface

```
binder_linux  (binder,hwbinder,vndbinder)   → Android IPC
ashmem_linux  | memfd (use_memfd=1)          → shared memory
v4l2loopback  (/dev/video10)                 → virtual camera
/dev/dri/*    (optional)                      → GPU passthrough
```

## Lifecycle of a phone

```
create ─► docker run redroid (props, /data mount, adb port, labels)
       ─► fingerprint generated + saved to data/<name>.fingerprint.json
provision ─► adb wait-for-boot
          ─► adb root
          ─► stability props        (anti-crash)
          ─► webview/chrome harden  (anti-crash)
          ─► fingerprint resetprop  (identity)
          ─► proxy apply            (network)
          ─► gps set                (location)
          ─► framework restart
ready  ─► control via ws-scrcpy, install apps, automate
```

## Why a manager instead of pure compose

The base `docker-compose.yml` boots a single reference phone so `make up` works
out of the box. Beyond that, phones are dynamic — created/destroyed at runtime
with per-phone fingerprints, proxies and resource limits — which is a poor fit
for static compose. `PhoneManager` (Docker SDK) is the single source of truth;
the dashboard mounts `/var/run/docker.sock` to drive sibling containers.

## Networking

All containers share the `cloudphone` bridge network. Inside it phones are
reachable as `redroid-N:5555`; on the host they map to `localhost:(5555+N)`.
ws-scrcpy and the dashboard talk to phones over the internal names.

## Data & persistence

- `data/redroid-N/` — Android `/data` (apps, accounts, settings) per phone.
- `data/<name>.fingerprint.json` — generated identity, re-applied each provision.
- `nuke` / `destroy --wipe` remove these; ordinary stop/restart preserve them.
