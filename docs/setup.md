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

Your laptop is x86_64, so the stock `redroid/redroid:13.0.0-latest` image runs
native and is fastest. The stock images are x86_64/arm64 **native** and do not
translate ARM — so an app with ARM-only native libs fails with
`INSTALL_FAILED_NO_MATCHING_ABIS`.

To run ARM-only apps on x86 you need a Redroid image that bundles a **native
bridge** (libndk_translation / libhoudini). These are community-built images,
not the stock tags. Point `REDROID_IMAGE` at one in `.env`; the `generic_x86_64`
profile already advertises arm in its `abilist`. Most apps that ship x86 libs
(the majority) work on the stock image with no extra setup. See
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
