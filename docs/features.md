# Features — deep dive

Mapped to the original feature list. Each entry says **how** it works and
**how to use** it.

## Redroid architecture & Docker Compose
`make up` builds the stack from `docker-compose.yml`. The reference phone plus
ws-scrcpy and the dashboard. Additional phones via the orchestrator. See
[architecture.md](architecture.md).

## ws-scrcpy integration
`docker/ws-scrcpy` builds the client from source and auto-connects phones. The
dashboard embeds it per phone (the **View** button). Direct UI at `:8000`.

## Multi-phone orchestration
`cloudphone create --count N`, `ls`, `start/stop/restart/destroy`. Each phone is
isolated (own `/data`, adb port, fingerprint, proxy). Limited by host RAM/CPU.

## GPU passthrough
`REDROID_GPU_MODE=host` + `/dev/dri` device mapping. Falls back to SwiftShader
software GL (`guest`) which needs no GPU and is the most crash-resistant. See
[troubleshooting.md](troubleshooting.md).

## Camera virtualization / getUserMedia / media upload
`scripts/camera-setup.sh image|video|stream <src>` pumps media into
`/dev/video10` (v4l2loopback). Map that node into a phone and apps' camera +
`getUserMedia` see the synthetic feed — the media-upload pipeline for
photo/video capture flows.

## WebGL renderer improvements
The stability layer pins HWUI to `skiagl` and routes WebGL through SwiftShader
(or mesa under host GPU), eliminating the blank-canvas / GPU-process-crash
failure modes.

## Audio devices
Redroid exposes a virtual audio HAL. Enable mic/speaker routing with
`androidboot.redroid_audio=1` (add to the boot command / `REDROID_*` env) and
the phone gets a usable audio device; capture/playback ride the container.

## Sensor emulation
Inject sensor values over adb, e.g. accelerometer/light/proximity via
`sensorservice`:
```bash
cloudphone shell redroid-0 "su -c 'cmd sensorservice set-sensor-value ...'"
```
GPS is handled separately (below).

## Device fingerprint management
`fingerprint.py` generates a consistent identity per phone (brand/model/build
fingerprint, serial, android_id, IMEI w/ valid Luhn, MACs). Deterministic from
the phone name, saved to `data/<name>.fingerprint.json`, re-applied each
provision. Profiles: Pixel 7/6, Galaxy S21, Redmi Note 11, generic x86_64; add
your own in `config/devices/`.

## Magisk + resetprop automation
`scripts/magisk-setup.sh <phone>` roots a phone and enables `resetprop`, which
provision uses to make the fingerprint stick against Play-services reads.

## Play Store compatibility
`scripts/install-gapps.sh <phone>` stages MindTheGapps and installs Play
services; then register the GSF id at google.com/android/uncertified. Limits in
[known-limitations.md](known-limitations.md).

## Chrome crash fixes / Persona crash investigation
Both are the same root cause — GL/Vulkan on a non-existent GPU. Fixed by the
stability props + WebView/Chrome flags (`--use-gl=swiftshader --disable-gpu
--in-process-gpu`, `debug.stagefright.ccodec=0`). Applied automatically on
`provision`; details in [troubleshooting.md](troubleshooting.md).

## ARM/x86 compatibility
x86_64 images run native. For ARM-only apps use a native-bridge Redroid tag
(libhoudini/libndk); the `abilist` advertises arm so installers accept the APK.

## Proxy engine
`cloudphone proxy <phone> --url <u> --mode http|socks5|transparent|browser|off`.
`transparent`/`socks5` use redsocks + iptables (need root); `http`/`browser`
need no root. Pools in `config/proxies.example.yaml`.

## GPS spoofing
`cloudphone gps <phone> --lat --lon`, or `gps.walk()` for routes. Uses mock
providers (`cmd location` with root, plus a broadcast for the non-root helper).

## Automation CLI
`cloudphone` (Typer) — full lifecycle + provision + install + gps + proxy +
shell + health. Scriptable for batch jobs.

## Web dashboard
FastAPI at `:8080` — create phones, live health, lifecycle buttons, embedded
scrcpy viewer, GPS API.

## Health monitoring
`cloudphone health` / `/api/health` — container status, boot state, CPU%, RAM,
SurfaceFlinger liveness, recent crash count from dropbox.

## Persistent storage
Per-phone bind mounts under `data/`; identities persisted as JSON. Survive
restart/recreate.

## Remote access
Put the dashboard + ws-scrcpy behind a TLS reverse proxy. See
[remote-access.md](remote-access.md).

## Docker optimization
Multi-stage images, slim runtime bases, healthchecks, resource limits, restart
policies, `make clean`.

## Security hardening
See [security.md](security.md).

## CI/CD
`.github/workflows/ci.yml` — lint + tests + compose validation + image builds.

## Testing
`make test` runs the pytest suite (fingerprint, proxy, config). Docker-dependent
paths are integration-tested on a real host.
