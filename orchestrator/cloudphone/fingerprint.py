"""Device fingerprint management.

Generates a self-consistent set of Android `ro.*` build properties for a phone
so it looks like a real handset. Properties are applied at runtime with
`resetprop` (via Magisk) so they survive reads from Play services / apps.

Also emits the *stability* props that stop common startup crashes (Chrome,
Persona, WebView, GL apps) inside a containerized/headless Android.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass, asdict

# Curated, internally-consistent real-device profiles.
DEVICE_PROFILES: dict[str, dict] = {
    "pixel_7": {
        "brand": "google",
        "manufacturer": "Google",
        "model": "Pixel 7",
        "device": "panther",
        "product": "panther",
        "board": "panther",
        "release": "13",
        "sdk": "33",
        "security_patch": "2023-08-05",
        "build_id": "TQ3A.230805.001",
        "incremental": "10316531",
        "abilist": "arm64-v8a,armeabi-v7a,armeabi",
    },
    "pixel_6": {
        "brand": "google",
        "manufacturer": "Google",
        "model": "Pixel 6",
        "device": "oriole",
        "product": "oriole",
        "board": "oriole",
        "release": "13",
        "sdk": "33",
        "security_patch": "2023-06-05",
        "build_id": "TQ3A.230605.012",
        "incremental": "10031313",
        "abilist": "arm64-v8a,armeabi-v7a,armeabi",
    },
    "samsung_s21": {
        "brand": "samsung",
        "manufacturer": "samsung",
        "model": "SM-G991B",
        "device": "o1s",
        "product": "o1sxxx",
        "board": "exynos2100",
        "release": "13",
        "sdk": "33",
        "security_patch": "2023-07-01",
        "build_id": "TP1A.220624.014",
        "incremental": "G991BXXU5DWGK",
        "abilist": "arm64-v8a,armeabi-v7a,armeabi",
    },
    "xiaomi_redmi_note11": {
        "brand": "Redmi",
        "manufacturer": "Xiaomi",
        "model": "22031116BG",
        "device": "spes",
        "product": "spes_global",
        "board": "spes",
        "release": "12",
        "sdk": "31",
        "security_patch": "2023-04-01",
        "build_id": "SP1A.210812.016",
        "incremental": "V13.0.10.0.SGCMIXM",
        "abilist": "arm64-v8a,armeabi-v7a,armeabi",
    },
    # x86 fallback profile — use when no ARM native-bridge image is in play.
    "generic_x86_64": {
        "brand": "Android",
        "manufacturer": "unknown",
        "model": "redroid13",
        "device": "redroid",
        "product": "redroid",
        "board": "redroid",
        "release": "13",
        "sdk": "33",
        "security_patch": "2023-08-05",
        "build_id": "TQ3A.230805.001",
        "incremental": "eng.cloudphone",
        "abilist": "x86_64,x86,arm64-v8a,armeabi-v7a,armeabi",
    },
}


@dataclass
class Fingerprint:
    profile: str
    serial: str
    android_id: str  # 64-bit settings_secure android_id (hex)
    gsf_id: str  # Google services framework id
    wifi_mac: str
    bt_mac: str
    imei: str
    build_fingerprint: str
    props: dict  # full ro.* prop map to resetprop

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def _rng(seed: str | None) -> random.Random:
    if seed is None:
        seed = str(time.time_ns()) + str(random.random())
    return random.Random(hashlib.sha256(seed.encode()).hexdigest())


def _mac(rng: random.Random, oui: str) -> str:
    tail = ":".join(f"{rng.randint(0, 255):02x}" for _ in range(3))
    return f"{oui}:{tail}"


def _luhn_check_digit(num: str) -> int:
    digits = [int(d) for d in num]
    for i in range(len(digits) - 1, -1, -2):
        digits[i] *= 2
        if digits[i] > 9:
            digits[i] -= 9
    return (10 - sum(digits) % 10) % 10


def _imei(rng: random.Random) -> str:
    body = "35" + "".join(str(rng.randint(0, 9)) for _ in range(12))
    return body + str(_luhn_check_digit(body))


def generate(profile: str = "pixel_7", seed: str | None = None) -> Fingerprint:
    """Build a complete, internally-consistent fingerprint for one phone.

    Pass a stable `seed` (e.g. the phone name) to get a deterministic identity
    that persists across recreation.
    """
    if profile not in DEVICE_PROFILES:
        raise ValueError(f"unknown profile {profile!r}; choose from {list(DEVICE_PROFILES)}")
    p = DEVICE_PROFILES[profile]
    rng = _rng(seed)

    serial = "".join(rng.choice("0123456789ABCDEF") for _ in range(12))
    android_id = "".join(rng.choice("0123456789abcdef") for _ in range(16))
    gsf_id = "".join(rng.choice("0123456789abcdef") for _ in range(16))
    wifi_mac = _mac(rng, "a4:50:46")  # plausible OUI
    bt_mac = _mac(rng, "a4:50:46")
    imei = _imei(rng)

    fp = (
        f"{p['brand']}/{p['product']}/{p['device']}:{p['release']}/"
        f"{p['build_id']}/{p['incremental']}:user/release-keys"
    )

    props = {
        "ro.product.brand": p["brand"],
        "ro.product.manufacturer": p["manufacturer"],
        "ro.product.model": p["model"],
        "ro.product.device": p["device"],
        "ro.product.name": p["product"],
        "ro.product.board": p["board"],
        "ro.product.cpu.abilist": p["abilist"],
        "ro.product.cpu.abilist64": ",".join(a for a in p["abilist"].split(",") if "64" in a),
        "ro.product.cpu.abilist32": ",".join(a for a in p["abilist"].split(",") if "64" not in a),
        "ro.build.version.release": p["release"],
        "ro.build.version.sdk": p["sdk"],
        "ro.build.version.security_patch": p["security_patch"],
        "ro.build.id": p["build_id"],
        "ro.build.display.id": p["build_id"],
        "ro.build.fingerprint": fp,
        "ro.bootimage.build.fingerprint": fp,
        "ro.build.tags": "release-keys",
        "ro.build.type": "user",
        "ro.boot.verifiedbootstate": "green",
        "ro.boot.flash.locked": "1",
        "ro.serialno": serial,
        "ro.boot.serialno": serial,
        # Hide container/emulator tells:
        "ro.kernel.qemu": "0",
        "ro.hardware": p["device"],
        "ro.product.first_api_level": p["sdk"],
    }

    return Fingerprint(
        profile=profile,
        serial=serial,
        android_id=android_id,
        gsf_id=gsf_id,
        wifi_mac=wifi_mac,
        bt_mac=bt_mac,
        imei=imei,
        build_fingerprint=fp,
        props=props,
    )


# ── Stability props ─────────────────────────────────────────────────────────
# Applied to *every* phone regardless of fingerprint. These are the props that
# stop the most common startup crashes inside headless/containerized Android.
def stability_props(gpu_mode: str = "guest") -> dict:
    props = {
        # Force a software-safe HWUI renderer path when there is no real GPU.
        # SkiaGL on SwiftShader is far more crash-resistant than Vulkan here.
        "debug.hwui.renderer": "skiagl",
        "ro.hardware.egl": "swiftshader" if gpu_mode == "guest" else "mesa",
        "ro.hardware.vulkan": "" if gpu_mode == "guest" else "mesa",
        # Chrome / WebView: disable GPU rasterization that segfaults on swiftshader.
        # (Mirrored into a chrome-command-line file by apps.harden_webview.)
        "debug.egl.hw": "0" if gpu_mode == "guest" else "1",
        # Stop the media stack from probing absent hardware codecs (Persona/most
        # camera-using apps crash here on first frame).
        "debug.stagefright.ccodec": "0",
        "media.stagefright.legacyencoder": "1",
        # Keep zygote/system_server from OOM-killing during cold start.
        "dalvik.vm.heapgrowthlimit": "256m",
        "dalvik.vm.heapsize": "512m",
        # Disable the boot animation (one less GL surface to crash on).
        "debug.sf.nobootanimation": "1",
    }
    return props
