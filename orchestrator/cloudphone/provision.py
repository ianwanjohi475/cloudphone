"""Post-boot provisioning: turn a freshly-booted phone into a ready one.

Order matters:
  1. wait for boot
  2. adb root + apply stability props  (stops startup crashes)
  3. harden WebView/Chrome
  4. apply fingerprint via resetprop    (device identity)
  5. apply proxy
  6. set location
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import apps, gps as gps_mod, proxy as proxy_mod
from .adb import Adb
from .fingerprint import Fingerprint, stability_props


@dataclass
class ProvisionResult:
    booted: bool
    steps: list[str]


def provision(
    address: str,
    fingerprint: Optional[Fingerprint] = None,
    gpu_mode: str = "guest",
    proxy_url: str = "",
    proxy_mode: str = "transparent",
    location: Optional[gps_mod.Location] = None,
    boot_timeout: int = 180,
) -> ProvisionResult:
    adb = Adb(address)
    steps: list[str] = []

    if not adb.wait_boot(timeout=boot_timeout):
        return ProvisionResult(booted=False, steps=["boot timed out"])
    steps.append("booted")

    adb.root()
    steps.append("adb root")

    # 1. Stability props — the anti-crash layer.
    for k, v in stability_props(gpu_mode).items():
        adb.resetprop(k, v)
    steps.append(f"applied {len(stability_props(gpu_mode))} stability props")

    # 2. WebView / Chrome hardening.
    steps.append(apps.harden_webview(adb))

    # 3. Device fingerprint.
    if fingerprint:
        for k, v in fingerprint.props.items():
            adb.resetprop(k, v)
        adb.shell(f"settings put secure android_id {fingerprint.android_id}", check=False)
        steps.append(f"applied fingerprint ({fingerprint.profile}, {len(fingerprint.props)} props)")

    # 4. Proxy.
    if proxy_url:
        spec = proxy_mod.ProxySpec.parse(proxy_url)
        steps.append(proxy_mod.apply(adb, proxy_mode, spec))

    # 5. Location.
    if location:
        gps_mod.enable_mock(adb)
        steps.append(gps_mod.set_location(adb, location))

    # Restart the framework so prop changes are picked up cleanly.
    adb.shell("su -c 'stop && start'", check=False)
    steps.append("framework restarted")

    return ProvisionResult(booted=True, steps=steps)
