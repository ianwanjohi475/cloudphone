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

## Quick start — native scrcpy (recommended)

One self-contained script: starts a phone with the correct image, applies the
anti-crash settings, optionally routes it through a proxy, and hands you the
`scrcpy` command. No `.env`, no web server, no Python needed.

```bash
# 0. Prereqs: Ubuntu + Docker + git  (WSL2 is fine)
git clone https://github.com/ianwanjohi475/cloudphone.git cloudphone && cd cloudphone

# 1. Load host kernel modules (binder / ashmem / v4l2loopback) — once per boot
sudo ./scripts/setup-host.sh
./scripts/doctor.sh

# 2. Start a phone (add a proxy with PROXY=host:port:user:pass)
./scripts/start-phone.sh
# or, proxied:
# PROXY="161.77.95.162:22325:user:pass" ./scripts/start-phone.sh

# 3. Open the phone in a native scrcpy window
sudo apt-get install -y scrcpy
scrcpy -s localhost:5555
```

Install an app:  `adb -s localhost:5555 install -r yourapp.apk`
Stop the phone:  `./scripts/stop-phone.sh`

> WSL2: scrcpy needs a GUI. Windows 11 (WSLg) shows it automatically; on
> Windows 10 run an X server and `export DISPLAY=:0` first.

## Optional — web stack (dashboard + ws-scrcpy)

If you prefer browser control and multi-phone orchestration instead of native
scrcpy:

```bash
cp .env.example .env          # ships the correct redroid:13.0.0-latest tag
make up                       # dashboard :8080, ws-scrcpy :8000
make install-cli              # PEP 668-safe venv install of the CLI
```

> Already have a stale `.env` failing with `redroid/redroid:13.0.0: not found`?
> Regenerate it: `cp .env.example .env` (the old template expanded a bare,
> non-existent tag).

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
