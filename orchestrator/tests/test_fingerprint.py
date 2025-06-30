import re

import pytest

from cloudphone.fingerprint import DEVICE_PROFILES, generate, stability_props


def test_all_profiles_generate():
    for profile in DEVICE_PROFILES:
        fp = generate(profile=profile, seed="phone-x")
        assert fp.props["ro.product.model"]
        assert fp.build_fingerprint.endswith("release-keys")
        assert "ro.build.fingerprint" in fp.props


def test_seed_is_deterministic():
    a = generate(profile="pixel_7", seed="redroid-0")
    b = generate(profile="pixel_7", seed="redroid-0")
    assert a.serial == b.serial
    assert a.android_id == b.android_id
    assert a.imei == b.imei


def test_distinct_seeds_differ():
    a = generate(profile="pixel_7", seed="redroid-0")
    b = generate(profile="pixel_7", seed="redroid-1")
    assert a.serial != b.serial
    assert a.imei != b.imei


def test_imei_luhn_valid():
    fp = generate(seed="abc")
    digits = [int(d) for d in fp.imei]
    assert len(digits) == 15
    # Luhn checksum over all 15 digits must be 0 mod 10.
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    assert total % 10 == 0


def test_android_id_format():
    fp = generate(seed="abc")
    assert re.fullmatch(r"[0-9a-f]{16}", fp.android_id)


def test_unknown_profile_raises():
    with pytest.raises(ValueError):
        generate(profile="nope")


def test_stability_props_guest_uses_swiftshader():
    props = stability_props("guest")
    assert props["ro.hardware.egl"] == "swiftshader"
    assert props["debug.hwui.renderer"] == "skiagl"


def test_stability_props_host_uses_mesa():
    assert stability_props("host")["ro.hardware.egl"] == "mesa"
