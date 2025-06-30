"""Thin adb wrapper used to talk to phones over TCP."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass


class AdbError(RuntimeError):
    pass


def _adb_bin() -> str:
    binary = shutil.which("adb")
    if not binary:
        raise AdbError("adb not found on PATH (install android-tools-adb)")
    return binary


@dataclass
class Adb:
    """Commands scoped to a single device address like 'redroid-0:5555'."""

    address: str
    timeout: int = 30

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        cmd = [_adb_bin(), "-s", self.address, *args]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)
        if check and proc.returncode != 0:
            raise AdbError(f"{' '.join(cmd)} -> {proc.returncode}: {proc.stderr.strip()}")
        return proc

    # connection -------------------------------------------------------------
    def connect(self) -> bool:
        out = subprocess.run(
            [_adb_bin(), "connect", self.address],
            capture_output=True,
            text=True,
            timeout=self.timeout,
        )
        return "connected" in out.stdout.lower()

    def wait_boot(self, timeout: int = 120) -> bool:
        """Block until sys.boot_completed=1 or timeout (seconds)."""
        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.connect()
                res = self._run("shell", "getprop", "sys.boot_completed", check=False)
                if res.stdout.strip() == "1":
                    return True
            except AdbError:
                pass
            time.sleep(3)
        return False

    # shell ------------------------------------------------------------------
    def shell(self, command: str, check: bool = True) -> str:
        return self._run("shell", command, check=check).stdout.strip()

    def root(self) -> str:
        return subprocess.run(
            [_adb_bin(), "-s", self.address, "root"], capture_output=True, text=True
        ).stdout.strip()

    def setprop(self, key: str, value: str) -> None:
        self.shell(f"setprop {key} '{value}'", check=False)

    def resetprop(self, key: str, value: str) -> None:
        """Persist a prop via Magisk's resetprop when available, else setprop."""
        if self.shell("command -v resetprop || true", check=False):
            self.shell(f"resetprop -n {key} '{value}'", check=False)
        else:
            self.setprop(key, value)

    def install(self, apk_path: str, reinstall: bool = True) -> str:
        args = ["install"]
        if reinstall:
            args.append("-r")
        args.append(apk_path)
        return self._run(*args).stdout.strip()

    def push(self, src: str, dst: str) -> None:
        self._run("push", src, dst)
