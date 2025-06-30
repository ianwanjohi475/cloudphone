# Setup

## 1. Host requirements

- Ubuntu 20.04+ (or any modern Linux with a kernel that has `binder`)
- Docker Engine 24+ with the **compose v2** plugin
- 8 GB RAM minimum (each phone ~2–4 GB), x86_64 CPU
- Your user in the `docker` group: `sudo usermod -aG docker $USER` (re-login)

## 2. Kernel modules

Redroid needs `binder` and either `ashmem` or `memfd`. The virtual camera needs
`v4l2loopback`. Load them all:

```bash
sudo ./scripts/setup-host.sh
```

This is idempotent and writes `/etc/modules-load.d/cloudphone.conf` so the
modules persist across reboots.

### If `binder_linux` is missing

```bash
sudo apt-get install -y linux-modules-extra-$(uname -r)
sudo modprobe binder_linux devices=binder,hwbinder,vndbinder
```

On kernels without binder at all (rare on Ubuntu), use the
[anbox/binder DKMS module](https://github.com/choff/anbox-modules).

### Virtual camera

```bash
sudo apt-get install -y v4l2loopback-dkms ffmpeg
sudo ./scripts/setup-host.sh        # creates /dev/video10
```

Verify everything:

```bash
./scripts/doctor.sh
```

## 3. Configure

```bash
cp .env.example .env
```

Key settings:

| Var | Meaning |
|-----|---------|
| `REDROID_IMAGE` | Android image/tag. Use an `*-arm-arm64` / native-bridge tag to run ARM-only apps on x86. |
| `REDROID_GPU_MODE` | `guest` (software, safest) or `host` (passthrough). |
| `REDROID_MEMORY` / `REDROID_CPUS` | Per-phone limits. |
| `ADB_BASE_PORT` | First phone's adb port; phone *n* = base + *n*. |
| `DEFAULT_PROXY` | Optional default upstream proxy for new phones. |

## 4. Launch

```bash
make up          # build images + start base stack
make ps          # see containers
make logs S=redroid-0
```

Dashboard at `http://localhost:8080`, ws-scrcpy at `http://localhost:8000`.

## 5. ARM vs x86 apps

Your laptop is x86_64, so x86 images are fastest. Many Play apps ship ARM-only
native libraries. To run them, use a Redroid image built with a **native
bridge** (libhoudini / libndk translation) — pick the matching
`redroid/redroid:<ver>_64only-arm-arm64`-style tag and set the
`generic_x86_64` profile's `abilist` (already includes arm). See
[`docs/features.md`](features.md#armx86-compatibility).

## 6. GPU passthrough (optional, faster)

```bash
# in .env
REDROID_GPU_MODE=host
REDROID_GPU_NODE=/dev/dri/renderD128
```

Then uncomment the `devices:` block in `docker-compose.yml` (or the CLI maps it
automatically). Requires matching mesa drivers on the host. If apps start
crashing, fall back to `guest` — see troubleshooting.
