"""Install any Android app file onto a phone.

Handles every format people actually download:

  .apk                         single APK
  .xapk  (APKPure)             split APKs + optional OBB data + manifest.json
  .apks  (SAI / bundletool)    split APKs
  .apkm  (APKMirror)           split APKs (unencrypted bundles)
  .zip                         any zip that contains APKs
  directory                    a folder of split APKs

Split bundles are filtered to the CPU ABIs the phone reports, OBB expansion
files are pushed to /sdcard/Android/obb/<package>/, runtime permissions are
granted at install, and adb's cryptic failure codes are turned into a sentence
that says what to do next.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .adb import Adb, _adb_bin

BUNDLE_SUFFIXES = {".xapk", ".apks", ".apkm", ".zip"}
KNOWN_ABIS = {"arm64_v8a", "armeabi_v7a", "armeabi", "x86", "x86_64", "mips", "mips64"}

# adb failure code -> what the user should do about it.
ERROR_HINTS = {
    "INSTALL_FAILED_NO_MATCHING_ABIS": (
        "This app only ships ARM code and this phone cannot translate it. "
        "Install it on a real phone instead (dashboard: Real phone, or `make real-phone`), "
        "which runs ARM apps."
    ),
    "INSTALL_FAILED_UPDATE_INCOMPATIBLE": (
        "A different build of this app is already installed (different signature). "
        "Uninstall the old one first, or install again with replace turned on."
    ),
    "INSTALL_FAILED_VERSION_DOWNGRADE": (
        "A newer version is already installed. Uninstall it first to go back to this version."
    ),
    "INSTALL_FAILED_OLDER_SDK": (
        "The app needs a newer Android version than this phone runs. "
        "Start the phone on a newer image (for example redroid 14)."
    ),
    "INSTALL_FAILED_DEPRECATED_SDK_VERSION": (
        "The app targets a very old Android version; retried with the low-target bypass."
    ),
    "INSTALL_FAILED_INSUFFICIENT_STORAGE": "The phone is out of storage. Uninstall something.",
    "INSTALL_FAILED_MISSING_SPLIT": (
        "This is only part of a split app. Download the full .xapk/.apks/.apkm bundle instead."
    ),
    "INSTALL_PARSE_FAILED_NO_CERTIFICATES": "The file is not signed or is damaged.",
    "INSTALL_PARSE_FAILED_NOT_APK": "That file is not an Android app.",
    "INSTALL_FAILED_INVALID_APK": "The APK is damaged or incomplete. Download it again.",
    "INSTALL_FAILED_TEST_ONLY": "Test-only app; retried with -t.",
}


class InstallError(RuntimeError):
    def __init__(self, code: str, detail: str):
        self.code = code
        self.detail = detail
        hint = ERROR_HINTS.get(code, "")
        super().__init__(f"{code}: {hint or detail}")

    @property
    def hint(self) -> str:
        return ERROR_HINTS.get(self.code, self.detail)


@dataclass
class Bundle:
    apks: list[Path]
    package: str = ""
    obb: list[tuple[Path, str]] = field(default_factory=list)  # (local file, device path)
    label: str = ""


@dataclass
class InstallResult:
    package: str
    apks: list[str]
    obb: list[str]
    output: str

    def to_dict(self) -> dict:
        return self.__dict__


# --------------------------------------------------------------------------- pure helpers
def classify(path: str | Path) -> str:
    """Return 'apk', 'bundle' or 'dir'. Raises ValueError for anything else."""
    p = Path(path)
    if p.is_dir():
        return "dir"
    suffix = p.suffix.lower()
    if suffix == ".apk":
        return "apk"
    if suffix in BUNDLE_SUFFIXES:
        return "bundle"
    # Some sites serve bundles without an extension; sniff the zip.
    if zipfile.is_zipfile(p):
        with zipfile.ZipFile(p) as z:
            names = z.namelist()
        if "AndroidManifest.xml" in names:
            return "apk"
        if any(n.lower().endswith(".apk") for n in names):
            return "bundle"
    raise ValueError(f"{p.name} is not an Android app (.apk, .xapk, .apks, .apkm or .zip)")


def split_abi(name: str) -> str | None:
    """'split_config.arm64_v8a.apk' -> 'arm64_v8a'; non-ABI splits -> None."""
    stem = Path(name).name.lower()
    stem = stem[:-4] if stem.endswith(".apk") else stem
    for part in stem.replace("-", "_").split("."):
        if part in KNOWN_ABIS:
            return part
    return None


def select_splits(apks: list[Path], abilist: list[str]) -> list[Path]:
    """Keep base + density/language splits, and only the ABI splits the phone runs.

    abilist is the phone's ro.product.cpu.abilist (e.g. ['x86_64', 'x86',
    'arm64-v8a', 'armeabi-v7a', 'armeabi'] on an image with ARM translation),
    in preference order. If no ABI split matches, everything is kept so the
    package manager reports the real error.
    """
    wanted = [a.replace("-", "_") for a in abilist]
    abi_splits = {p: split_abi(p.name) for p in apks}
    present = [a for a in wanted if a in abi_splits.values()]
    if not present:
        return list(apks)
    # One native ABI family is enough: prefer the device's first supported ABI.
    best = present[0]
    return [p for p in apks if abi_splits[p] in (None, best)]


def parse_failure(output: str) -> str:
    m = re.search(r"(INSTALL_[A-Z_]+)", output)
    return m.group(1) if m else "INSTALL_FAILED"


def extract_bundle(path: Path, workdir: Path) -> Bundle:
    with zipfile.ZipFile(path) as z:
        z.extractall(workdir)
    apks = sorted(p for p in workdir.rglob("*.apk") if p.is_file())
    # .apks from bundletool keep splits under splits/; standalones/ holds
    # pre-merged alternatives that must not be mixed with the splits.
    if any("splits" in p.parts for p in apks):
        apks = [p for p in apks if not ({"standalone", "standalones"} & set(p.parts))]
    if not apks:
        raise ValueError(f"{path.name} has no APK files inside")
    bundle = Bundle(apks=apks)
    manifest = workdir / "manifest.json"  # XAPK
    if manifest.exists():
        try:
            meta = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            meta = {}
        bundle.package = meta.get("package_name", "")
        bundle.label = meta.get("name", "")
        for exp in meta.get("expansions", []) or []:
            local = workdir / exp.get("file", "")
            dest = exp.get("install_path") or exp.get("file", "")
            if local.is_file() and dest:
                bundle.obb.append((local, "/sdcard/" + dest.lstrip("/")))
    # OBB files that are present but not declared.
    declared = {str(p) for p, _ in bundle.obb}
    for obb in workdir.rglob("*.obb"):
        if str(obb) in declared:
            continue
        parts = obb.relative_to(workdir).parts
        if "obb" in parts:
            rel = "/".join(parts[parts.index("obb") - 1 :])  # Android/obb/<pkg>/file.obb
            bundle.obb.append((obb, "/sdcard/" + rel))
    return bundle


# --------------------------------------------------------------------------- device side
def device_abis(adb: Adb) -> list[str]:
    raw = adb.shell("getprop ro.product.cpu.abilist", check=False).strip()
    return [a for a in raw.split(",") if a]


def can_run_arm(adb: Adb) -> bool:
    return any(a.startswith("arm") for a in device_abis(adb))


def _run_install(address: str, apks: list[Path], extra: list[str]) -> subprocess.CompletedProcess:
    verb = "install-multiple" if len(apks) > 1 else "install"
    cmd = [_adb_bin(), "-s", address, verb, "-r", *extra, *map(str, apks)]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=900)


def install_apks(
    adb: Adb, apks: list[Path], replace_incompatible: bool = False, package: str = ""
) -> str:
    """Install one APK or a split set, retrying the recoverable failures."""
    attempts = [["-g"], ["-g", "-t"], ["-g", "-t", "--bypass-low-target-sdk-block"], []]
    last = ""
    tried_replace = False
    i = 0
    while i < len(attempts):
        proc = _run_install(adb.address, apks, attempts[i])
        out = (proc.stdout + "\n" + proc.stderr).strip()
        if proc.returncode == 0 and "Failure" not in out:
            return out
        last = out
        code = parse_failure(out)
        if (
            code == "INSTALL_FAILED_UPDATE_INCOMPATIBLE"
            and replace_incompatible
            and not tried_replace
        ):
            pkg = package or _package_from_error(out)
            if pkg:
                adb.shell(f"pm uninstall {pkg}", check=False)
                tried_replace = True
                continue
        recoverable = code in {
            "INSTALL_FAILED_TEST_ONLY",
            "INSTALL_FAILED_DEPRECATED_SDK_VERSION",
        } or ("unknown option" in out.lower() or "unrecognized option" in out.lower())
        if not recoverable:
            raise InstallError(code, out)
        i += 1
    raise InstallError(parse_failure(last), last)


def _package_from_error(out: str) -> str:
    m = re.search(r"Package ([\w.]+) signatures", out) or re.search(r"package ([\w.]+)", out)
    return m.group(1) if m else ""


def installed_packages(adb: Adb) -> set[str]:
    out = adb.shell("pm list packages -3", check=False)
    return {ln.split(":", 1)[1].strip() for ln in out.splitlines() if ln.startswith("package:")}


def install_any(adb: Adb, path: str | Path, replace_incompatible: bool = False) -> InstallResult:
    """Install an .apk, split bundle (.xapk/.apks/.apkm/.zip) or folder of APKs."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    kind = classify(p)
    before = installed_packages(adb)
    abis = device_abis(adb)
    with tempfile.TemporaryDirectory(prefix="cloudphone-install-") as tmp:
        if kind == "apk":
            bundle = Bundle(apks=[p])
        elif kind == "dir":
            bundle = Bundle(apks=sorted(p.glob("*.apk")))
            if not bundle.apks:
                raise ValueError(f"no .apk files in {p}")
        else:
            bundle = extract_bundle(p, Path(tmp))
        apks = select_splits(bundle.apks, abis) if len(bundle.apks) > 1 else bundle.apks
        out = install_apks(
            adb, apks, replace_incompatible=replace_incompatible, package=bundle.package
        )
        pushed = []
        for local, dest in bundle.obb:
            adb.shell(f"mkdir -p '{str(Path(dest).parent)}'", check=False)
            adb.push(str(local), dest)
            pushed.append(dest)
    new = sorted(installed_packages(adb) - before)
    package = bundle.package or (new[0] if new else "")
    return InstallResult(package=package, apks=[a.name for a in apks], obb=pushed, output=out)


def uninstall(adb: Adb, package: str) -> str:
    if not re.fullmatch(r"[\w.]+", package):
        raise ValueError("bad package name")
    return adb.shell(f"pm uninstall {package}", check=False)


def launch(adb: Adb, package: str) -> str:
    if not re.fullmatch(r"[\w.]+", package):
        raise ValueError("bad package name")
    return adb.shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1", check=False)


def app_list(adb: Adb) -> list[dict]:
    """Third-party apps with their version, for the dashboard."""
    out = []
    for pkg in sorted(installed_packages(adb)):
        ver = adb.shell(f"dumpsys package {pkg} | grep -m1 versionName", check=False)
        out.append({"package": pkg, "version": ver.split("=", 1)[-1].strip() if "=" in ver else ""})
    return out
