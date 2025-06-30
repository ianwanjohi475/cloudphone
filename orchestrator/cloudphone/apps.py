"""App installation + crash-hardening (Chrome/WebView/Persona) and Play Store."""

from __future__ import annotations

from pathlib import Path

from .adb import Adb

# Chrome/WebView flags that stop GPU-process segfaults on software rendering.
CHROME_FLAGS = (
    "chrome --disable-gpu --disable-gpu-compositing --disable-software-rasterizer "
    "--disable-gpu-rasterization --use-gl=swiftshader --in-process-gpu "
    "--no-sandbox --disable-features=Vulkan"
)


def install_apk(adb: Adb, apk: str) -> str:
    """Install a local .apk (or a directory of split apks)."""
    p = Path(apk)
    if not p.exists():
        raise FileNotFoundError(apk)
    if p.is_dir():
        splits = sorted(str(x) for x in p.glob("*.apk"))
        if not splits:
            raise FileNotFoundError(f"no .apk files in {apk}")
        # install-multiple for split APKs (App Bundles).
        import shutil
        import subprocess

        adb_bin = shutil.which("adb")
        cmd = [adb_bin, "-s", adb.address, "install-multiple", "-r", *splits]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip())
        return out.stdout.strip()
    return adb.install(apk)


def harden_webview(adb: Adb) -> str:
    """Write Chrome/WebView command-line flags to prevent startup crashes."""
    for path in ("/data/local/tmp/chrome-command-line", "/data/local/tmp/webview-command-line"):
        adb.shell(f"echo '{CHROME_FLAGS}' > {path}", check=False)
    # Allow the debug command line to be read without root.
    adb.shell("settings put global webview_multiprocess 0", check=False)
    adb.shell("setprop debug.webview.disable_vulkan 1", check=False)
    return "webview/chrome hardened (swiftshader, no-gpu)"


def install_play_store(adb: Adb) -> str:
    """Install OpenGApps/MindTheGapps-style Play services.

    Redroid ships AOSP without GMS. This pushes the gapps package staged under
    /data/local/tmp/gapps and runs the on-device installer, then prompts the
    user to register the device's GSF id at google.com/android/uncertified.
    """
    staged = adb.shell("ls /data/local/tmp/gapps 2>/dev/null || true", check=False)
    if not staged:
        return (
            "No gapps staged. Run ./scripts/install-gapps.sh <phone> to fetch + "
            "push MindTheGapps, then re-run."
        )
    adb.shell("su -c 'sh /data/local/tmp/gapps/install.sh'", check=False)
    gsf = adb.shell(
        "content query --uri content://com.google.android.gsf.gservices "
        "--projection value --where \"name='android_id'\" 2>/dev/null || true",
        check=False,
    )
    return f"gapps installed. Register this GSF id at google.com/android/uncertified: {gsf}"


def list_packages(adb: Adb, third_party_only: bool = True) -> list[str]:
    flag = "-3" if third_party_only else ""
    out = adb.shell(f"pm list packages {flag}", check=False)
    return sorted(
        line.split(":", 1)[-1] for line in out.splitlines() if line.startswith("package:")
    )
