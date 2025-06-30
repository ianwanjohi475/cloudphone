# ☁️ cloudphone

Self-hosted **cloud-phone farm** that runs real Android instances in Docker on
an Ubuntu host, controllable from your browser via **scrcpy**. Built on
[Redroid](https://github.com/remote-android/redroid-doc) + [ws-scrcpy](https://github.com/NetrisTV/ws-scrcpy),
with a Python orchestrator, a web dashboard, and a full automation CLI.

> Runs on a normal Ubuntu PC/laptop with Docker. No phone hardware, no cloud
> account required.

---

## Features

| Area | What you get |
|------|--------------|
| **Android in Docker** | Redroid x86_64 / ARM-translation images, one container per phone |
| **Browser control** | ws-scrcpy live screen + touch/keyboard, embedded in the dashboard |
| **Multi-phone** | Create/stop/destroy N phones; each isolated with its own data + adb port |
| **Anti-crash** | Stability prop layer + WebView/Chrome hardening that stops the classic Chrome/Persona/GL startup crashes |
| **App install** | Single APK, split-APK bundles, and a Play Store (GApps) path |
| **Fingerprints** | Deterministic, internally-consistent device identities (serial, android_id, IMEI, MACs, full build fingerprint) per phone |
| **Magisk + resetprop** | Root + persistent prop spoofing automation |
| **Proxy engine** | Per-phone `http`, `socks5`, `transparent` (iptables+redsocks), and `browser-only` modes |
| **GPS spoofing** | Fixed location + route walking via mock providers |
| **Camera / media** | v4l2loopback virtual camera fed by image/video/RTSP (getUserMedia & upload flows) |
| **Sensors & audio** | Sensor injection + virtual audio devices |
| **GPU** | Software (SwiftShader) by default; host GPU passthrough when `/dev/dri` is available |
| **Ops** | Health monitoring, persistent storage, web dashboard, automation CLI |
| **Remote access** | Reverse-proxy + TLS recipe for accessing the farm off-host |
| **Quality** | Test suite, CI, security-hardening guide, full docs |

See [`docs/features.md`](docs/features.md) for the per-feature deep dive and
[`docs/known-limitations.md`](docs/known-limitations.md) for what is **not**
solvable in software (hardware-backed attestation, ML liveness).

---

## Quick start

```bash
# 0. Prereqs: Ubuntu + Docker (with the compose v2 plugin) + git
git clone <this-repo> cloudphone && cd cloudphone

# 1. Load host kernel modules (binder / ashmem / v4l2loopback) — once per boot
sudo ./scripts/setup-host.sh
./scripts/doctor.sh           # verify the host is ready

# 2. Configure and launch the base stack (1 phone + ws-scrcpy + dashboard)
cp .env.example .env          # edit if you like
make up

# 3. Open the dashboard
#    Dashboard : http://localhost:8080
#    ws-scrcpy : http://localhost:8000
```

The dashboard lists your phone, shows health, and a **View** button opens the
live screen. Click **+ New phone** to scale out.

### CLI

```bash
make install-cli                       # pip install -e ./orchestrator

cloudphone doctor                      # host check
cloudphone create --count 3 --profile pixel_7
cloudphone ls
cloudphone provision redroid-0 \       # boot-wait + anti-crash + fingerprint + proxy + gps
    --proxy socks5://user:pass@host:1080 --proxy-mode transparent \
    --lat 40.7128 --lon -74.0060
cloudphone install redroid-0 ./app.apk
cloudphone gps redroid-0 --lat 51.5 --lon -0.12
cloudphone proxy redroid-0 --url http://1.2.3.4:8080 --mode http
cloudphone health
cloudphone serve                       # run the dashboard directly
```

---

## How "no app crashes on startup" works

Containerized/headless Android has no real GPU, which is what kills Chrome,
Persona, WebView and most GL apps on first launch. cloudphone fixes this in
three layers, applied automatically on `provision`:

1. **Boot props** — `gpu.mode=guest` (SwiftShader software GL) + `use_memfd`.
2. **Stability props** — force `skiagl` HWUI, disable Vulkan/hw codec probing,
   raise the zygote heap, kill the boot animation. See
   `fingerprint.stability_props()`.
3. **WebView/Chrome flags** — `--use-gl=swiftshader --disable-gpu --in-process-gpu`
   written to the command-line files. See `apps.harden_webview()`.

When you pass through a real GPU (`REDROID_GPU_MODE=host` + `/dev/dri`), the
same layers switch to the mesa/hardware path. See
[`docs/troubleshooting.md`](docs/troubleshooting.md).

---

## Architecture

```
                ┌────────────── browser ──────────────┐
                │  Dashboard (:8080)   ws-scrcpy (:8000)│
                └───────┬───────────────────┬──────────┘
                        │ REST              │ WebSocket (scrcpy)
                ┌───────▼───────┐   ┌───────▼────────┐
                │  Orchestrator │   │   ws-scrcpy    │
                │ (FastAPI+CLI) │   │  (adb client)  │
                │  docker SDK   │   └───────┬────────┘
                └───────┬───────┘           │ adb
       ┌────────────────┼───────────────────┼────────────┐
   ┌───▼────┐      ┌────▼───┐           ┌────▼───┐
   │redroid0│ …    │redroid1│    …      │redroidN│   (privileged containers)
   │ /data  │      │ /data  │           │ /data  │   persistent per-phone
   └────────┘      └────────┘           └────────┘
            host kernel: binder + ashmem/memfd + v4l2loopback
```

Full write-up in [`docs/architecture.md`](docs/architecture.md).

---

## Repo layout

```
docker-compose.yml      base stack (1 phone + ws-scrcpy + dashboard)
Makefile                up / down / logs / test …
scripts/                host setup, doctor, apk/gapps/magisk/camera helpers
orchestrator/           Python package: manager, CLI, dashboard, proxy, gps, …
docker/                 ws-scrcpy + dashboard images
config/                 device profiles + proxy pool examples
docs/                   architecture, setup, features, troubleshooting, limits
.github/workflows/      CI
```

## Status & limitations

This gives you a working, scriptable Android farm for development, testing,
automation and privacy use-cases. It **cannot** defeat hardware-backed
attestation (Play Integrity `STRONG`/`HARDWARE`) or camera-based ML liveness —
those require a real TEE and a real sensor. Details and the realistic ceiling
are in [`docs/known-limitations.md`](docs/known-limitations.md).

MIT licensed. Use responsibly and only where you're authorized to.
