"""Health monitoring for phones."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

from .adb import Adb
from .manager import Phone


@dataclass
class Health:
    name: str
    container_status: str
    booted: bool
    boot_completed: str
    cpu_pct: Optional[float]
    mem_mb: Optional[float]
    surfaceflinger: bool  # is the display stack alive
    crashes_recent: int  # entries in dropbox/crash logs
    online: bool

    def to_dict(self) -> dict:
        return asdict(self)


def check(phone: Phone, container=None) -> Health:
    adb = Adb(phone.adb_address)
    online = adb.connect()
    boot = adb.shell("getprop sys.boot_completed", check=False) if online else ""
    sf = (
        bool(adb.shell("dumpsys SurfaceFlinger --list 2>/dev/null | head -1", check=False))
        if online
        else False
    )
    crashes = 0
    if online:
        out = adb.shell(
            "ls /data/system/dropbox 2>/dev/null | grep -c crash || echo 0", check=False
        )
        try:
            crashes = int(out.strip() or 0)
        except ValueError:
            crashes = 0

    cpu = mem = None
    if container is not None:
        cpu, mem = _container_stats(container)

    return Health(
        name=phone.name,
        container_status=phone.status,
        booted=boot == "1",
        boot_completed=boot,
        cpu_pct=cpu,
        mem_mb=mem,
        surfaceflinger=sf,
        crashes_recent=crashes,
        online=online,
    )


def _container_stats(container):
    try:
        s = container.stats(stream=False)
        cpu_delta = (
            s["cpu_stats"]["cpu_usage"]["total_usage"]
            - s["precpu_stats"]["cpu_usage"]["total_usage"]
        )
        sys_delta = s["cpu_stats"]["system_cpu_usage"] - s["precpu_stats"].get(
            "system_cpu_usage", 0
        )
        ncpu = s["cpu_stats"].get("online_cpus") or 1
        cpu_pct = (cpu_delta / sys_delta) * ncpu * 100 if sys_delta > 0 else 0.0
        mem_mb = s["memory_stats"].get("usage", 0) / (1024 * 1024)
        return round(cpu_pct, 1), round(mem_mb, 1)
    except (KeyError, ZeroDivisionError, TypeError):
        return None, None
