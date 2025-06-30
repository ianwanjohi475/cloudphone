# Troubleshooting

## Phone won't boot / container restarts

```bash
make logs S=redroid-0
./scripts/doctor.sh
```

- **binder missing** → `sudo ./scripts/setup-host.sh`; install
  `linux-modules-extra-$(uname -r)`.
- **`Read-only file system` / data errors** → wipe and recreate:
  `cloudphone destroy redroid-0 --wipe && cloudphone create`.
- **Stuck before `sys.boot_completed`** → usually GPU. Set
  `REDROID_GPU_MODE=guest` and recreate.

## Chrome / Persona / a GL app crashes on startup

This is the #1 issue and it's almost always the GPU path. The fix is applied by
`cloudphone provision`, but if you launched an app before provisioning:

```bash
cloudphone provision redroid-0          # re-applies stability + webview flags
# or manually:
cloudphone shell redroid-0 "setprop debug.hwui.renderer skiagl"
cloudphone shell redroid-0 "echo 'chrome --use-gl=swiftshader --disable-gpu --in-process-gpu --no-sandbox' > /data/local/tmp/chrome-command-line"
```

Checklist:
1. `REDROID_GPU_MODE=guest` (software) unless host GPU is verified working.
2. Stability props applied (`getprop debug.hwui.renderer` → `skiagl`).
3. WebView flags present (`/data/local/tmp/chrome-command-line`).
4. Enough RAM — raise `REDROID_MEMORY` if logcat shows `lowmemorykiller`.

```bash
cloudphone shell redroid-0 "logcat -d | grep -iE 'crash|fatal|gl |vulkan'"
```

## Host GPU passthrough makes things worse

Mesa/driver mismatch crashes more apps than software GL. Revert:
```bash
# .env
REDROID_GPU_MODE=guest
```
and recreate the phone. Only use `host` after `glxinfo`/`vainfo` confirm the
host stack is healthy and `/dev/dri/renderD128` is mappable.

## App won't install ("INSTALL_FAILED_NO_MATCHING_ABIS")

The APK is ARM-only and you're on an x86 image without translation. Switch
`REDROID_IMAGE` to a native-bridge tag (see setup.md §5), recreate, retry.

## Play Store says "device not certified"

Register the GSF id (printed by `install-gapps.sh`) at
google.com/android/uncertified, wait a few minutes, clear Play Store data.

## ws-scrcpy shows no devices

```bash
docker exec cloudphone-ws-scrcpy adb devices
docker exec cloudphone-ws-scrcpy adb connect redroid-0:5555
```
Confirm the phone is `running` and booted (`cloudphone health`).

## Proxy not taking effect

`transparent`/`socks5` need root — run `scripts/magisk-setup.sh` first. Verify:
```bash
cloudphone shell redroid-0 "su -c 'iptables -t nat -L OUTPUT -n'"
cloudphone shell redroid-0 "curl -s https://ifconfig.me"
```
