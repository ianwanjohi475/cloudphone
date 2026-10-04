import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from cloudphone import packages


def _zip(path: Path, files: dict) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def test_classify(tmp_path):
    apk = tmp_path / "a.apk"
    apk.write_bytes(b"x")
    assert packages.classify(apk) == "apk"
    for ext in (".xapk", ".apks", ".apkm", ".zip", ".XAPK"):
        f = tmp_path / f"b{ext}"
        f.write_bytes(b"x")
        assert packages.classify(f) == "bundle"
    assert packages.classify(tmp_path) == "dir"
    # Extension-less downloads are sniffed.
    sniff_apk = _zip(tmp_path / "download1", {"AndroidManifest.xml": "", "classes.dex": ""})
    assert packages.classify(sniff_apk) == "apk"
    sniff_bundle = _zip(tmp_path / "download2", {"base.apk": ""})
    assert packages.classify(sniff_bundle) == "bundle"
    junk = tmp_path / "notes.txt"
    junk.write_text("hi")
    with pytest.raises(ValueError):
        packages.classify(junk)


def test_split_abi():
    assert packages.split_abi("split_config.arm64_v8a.apk") == "arm64_v8a"
    assert packages.split_abi("config.armeabi-v7a.apk") == "armeabi_v7a"
    assert packages.split_abi("split_config.x86_64.apk") == "x86_64"
    assert packages.split_abi("split_config.xxhdpi.apk") is None
    assert packages.split_abi("base.apk") is None


def test_select_splits_prefers_first_device_abi():
    names = [
        "base.apk",
        "split_config.arm64_v8a.apk",
        "split_config.armeabi_v7a.apk",
        "split_config.x86_64.apk",
        "split_config.en.apk",
    ]
    apks = [Path(n) for n in names]
    got = [p.name for p in packages.select_splits(apks, ["x86_64", "arm64-v8a"])]
    assert got == ["base.apk", "split_config.x86_64.apk", "split_config.en.apk"]
    # ARM-only bundle on a phone with ARM translation: arm64 is picked.
    arm_only = [Path(n) for n in names if "x86" not in n]
    got = [p.name for p in packages.select_splits(arm_only, ["x86_64", "x86", "arm64-v8a"])]
    assert got == ["base.apk", "split_config.arm64_v8a.apk", "split_config.en.apk"]
    # Nothing matches: keep everything so pm reports the real error.
    assert packages.select_splits(arm_only, ["x86_64"]) == arm_only


def test_parse_failure_and_hint():
    out = "Failure [INSTALL_FAILED_NO_MATCHING_ABIS: Failed to extract native libraries]"
    assert packages.parse_failure(out) == "INSTALL_FAILED_NO_MATCHING_ABIS"
    assert packages.parse_failure("weird") == "INSTALL_FAILED"
    err = packages.InstallError("INSTALL_FAILED_NO_MATCHING_ABIS", out)
    assert "real phone" in err.hint


def test_extract_xapk_with_obb(tmp_path):
    manifest = {
        "package_name": "com.example.game",
        "name": "Game",
        "expansions": [
            {
                "file": "Android/obb/com.example.game/main.7.com.example.game.obb",
                "install_location": "EXTERNAL_STORAGE",
                "install_path": "Android/obb/com.example.game/main.7.com.example.game.obb",
            }
        ],
    }
    xapk = _zip(
        tmp_path / "game.xapk",
        {
            "manifest.json": json.dumps(manifest),
            "com.example.game.apk": "base",
            "config.arm64_v8a.apk": "arm",
            "Android/obb/com.example.game/main.7.com.example.game.obb": "data",
            "Android/obb/com.example.game/patch.7.com.example.game.obb": "patch",
        },
    )
    work = tmp_path / "work"
    work.mkdir()
    b = packages.extract_bundle(xapk, work)
    assert b.package == "com.example.game"
    assert sorted(p.name for p in b.apks) == ["com.example.game.apk", "config.arm64_v8a.apk"]
    dests = sorted(d for _, d in b.obb)
    assert dests == [
        "/sdcard/Android/obb/com.example.game/main.7.com.example.game.obb",
        "/sdcard/Android/obb/com.example.game/patch.7.com.example.game.obb",
    ]


def test_extract_bundletool_apks_skips_standalone(tmp_path):
    apks = _zip(
        tmp_path / "app.apks",
        {
            "splits/base-master.apk": "",
            "splits/base-arm64_v8a.apk": "",
            "standalones/standalone-arm64_v8a.apk": "",
            "toc.pb": "",
        },
    )
    work = tmp_path / "w"
    work.mkdir()
    b = packages.extract_bundle(apks, work)
    assert all("standalone" not in str(p) for p in b.apks)
    assert len(b.apks) == 2


def test_extract_rejects_empty_bundle(tmp_path):
    z = _zip(tmp_path / "x.zip", {"readme.txt": "no apps"})
    work = tmp_path / "w"
    work.mkdir()
    with pytest.raises(ValueError):
        packages.extract_bundle(z, work)


class FakeAdb:
    address = "emu:5555"

    def __init__(self):
        self.shell_calls = []

    def shell(self, cmd, check=True):
        self.shell_calls.append(cmd)
        return ""


def _proc(rc, out):
    return subprocess.CompletedProcess([], rc, stdout=out, stderr="")


def test_install_retries_test_only(monkeypatch):
    calls = []
    results = [_proc(1, "Failure [INSTALL_FAILED_TEST_ONLY]"), _proc(0, "Success")]

    def fake_run(address, apks, extra):
        calls.append(extra)
        return results.pop(0)

    monkeypatch.setattr(packages, "_run_install", fake_run)
    assert packages.install_apks(FakeAdb(), [Path("a.apk")]) == "Success"
    assert calls == [["-g"], ["-g", "-t"]]


def test_install_replaces_incompatible_when_asked(monkeypatch):
    results = [
        _proc(
            1, "Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: Package com.x signatures do not match]"
        ),
        _proc(0, "Success"),
    ]
    monkeypatch.setattr(packages, "_run_install", lambda *a: results.pop(0))
    adb = FakeAdb()
    packages.install_apks(adb, [Path("a.apk")], replace_incompatible=True)
    assert adb.shell_calls == ["pm uninstall com.x"]


def test_install_raises_with_hint(monkeypatch):
    monkeypatch.setattr(
        packages,
        "_run_install",
        lambda *a: _proc(1, "Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE: Package com.x ...]"),
    )
    with pytest.raises(packages.InstallError) as e:
        packages.install_apks(FakeAdb(), [Path("a.apk")])
    assert e.value.code == "INSTALL_FAILED_UPDATE_INCOMPATIBLE"
    assert "replace" in e.value.hint


def test_package_name_validation():
    with pytest.raises(ValueError):
        packages.uninstall(FakeAdb(), "com.x; reboot")
    with pytest.raises(ValueError):
        packages.launch(FakeAdb(), "$(id)")
