"""cloudphone automation CLI.

cloudphone doctor
cloudphone create --count 3 --profile pixel_7
cloudphone ls
cloudphone provision redroid-0 --proxy socks5://user:pass@host:1080
cloudphone install redroid-0 ./app.apk
cloudphone gps redroid-0 --lat 40.7128 --lon -74.0060
cloudphone proxy redroid-0 --url http://1.2.3.4:8080 --mode http
cloudphone health
cloudphone serve            # web dashboard
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import apps as apps_mod
from . import gps as gps_mod
from . import proxy as proxy_mod
from .adb import Adb
from .config import SETTINGS
from .fingerprint import DEVICE_PROFILES

app = typer.Typer(add_completion=False, help="Self-hosted cloud-phone farm (Redroid + ws-scrcpy).")
console = Console()


def _manager():
    from .manager import PhoneManager

    return PhoneManager()


@app.command()
def doctor():
    """Check host prerequisites."""
    import subprocess
    from pathlib import Path

    script = Path(__file__).resolve().parents[2] / "scripts" / "doctor.sh"
    raise typer.Exit(subprocess.call(["bash", str(script)]))


@app.command()
def create(
    count: int = typer.Option(1, help="How many phones to create."),
    profile: str = typer.Option("pixel_7", help=f"Device profile: {', '.join(DEVICE_PROFILES)}"),
    proxy: Optional[str] = typer.Option(None, help="Default proxy url for these phones."),
):
    """Create one or more phones."""
    mgr = _manager()
    phones = mgr.create_many(count, profile=profile, proxy=proxy)
    for p in phones:
        console.print(
            f"[green]created[/] {p.name}  adb=localhost:{p.adb_port}  profile={p.profile}"
        )
    console.print(f"\nProvision them once booted:  [cyan]cloudphone provision {phones[0].name}[/]")


@app.command("ls")
def list_phones():
    """List phones."""
    mgr = _manager()
    table = Table("name", "status", "index", "adb", "profile", "proxy")
    for p in mgr.list():
        table.add_row(
            p.name, p.status, str(p.index), f"localhost:{p.adb_port}", p.profile, p.proxy or "-"
        )
    console.print(table)


@app.command()
def start(name: str):
    """Start a stopped phone."""
    _manager().start(name)
    console.print(f"[green]started[/] {name}")


@app.command()
def stop(name: str):
    """Stop a phone."""
    _manager().stop(name)
    console.print(f"[yellow]stopped[/] {name}")


@app.command()
def restart(name: str):
    """Restart a phone."""
    _manager().restart(name)
    console.print(f"[green]restarted[/] {name}")


@app.command()
def destroy(
    name: str, wipe: bool = typer.Option(False, help="Also delete persistent data + identity.")
):
    """Remove a phone."""
    _manager().destroy(name, wipe=wipe)
    console.print(f"[red]destroyed[/] {name}{' (wiped)' if wipe else ''}")


@app.command()
def provision(
    name: str,
    proxy: Optional[str] = typer.Option(None, help="Proxy url."),
    proxy_mode: str = typer.Option("transparent", help="http|socks5|transparent|browser"),
    lat: Optional[float] = typer.Option(None),
    lon: Optional[float] = typer.Option(None),
    boot_timeout: int = typer.Option(180),
):
    """Apply stability props, fingerprint, webview hardening, proxy and GPS."""
    from .provision import provision as do_provision

    mgr = _manager()
    phone = mgr.get(name)
    fp = mgr.load_fingerprint(name)
    loc = gps_mod.Location(lat=lat, lon=lon) if lat is not None and lon is not None else None
    console.print(f"[cyan]provisioning[/] {name} (waiting for boot, up to {boot_timeout}s)…")
    res = do_provision(
        phone.adb_address,
        fingerprint=fp,
        gpu_mode=SETTINGS.gpu_mode,
        proxy_url=proxy or phone.proxy or "",
        proxy_mode=proxy_mode,
        location=loc,
        boot_timeout=boot_timeout,
    )
    for s in res.steps:
        console.print(f"  [green]✓[/] {s}" if res.booted else f"  [red]✗[/] {s}")


@app.command()
def install(name: str, apk: str = typer.Argument(..., help="Path to .apk or split-apk dir.")):
    """Install an app from a local apk."""
    phone = _manager().get(name)
    adb = Adb(phone.adb_address)
    adb.connect()
    console.print(apps_mod.install_apk(adb, apk))


@app.command()
def gps(name: str, lat: float = typer.Option(...), lon: float = typer.Option(...)):
    """Set a fixed GPS location."""
    phone = _manager().get(name)
    adb = Adb(phone.adb_address)
    adb.connect()
    gps_mod.enable_mock(adb)
    console.print(gps_mod.set_location(adb, gps_mod.Location(lat=lat, lon=lon)))


@app.command()
def proxy(
    name: str,
    url: Optional[str] = typer.Option(None, help="Proxy url; omit with --mode off to disable."),
    mode: str = typer.Option("transparent", help="http|socks5|transparent|browser|off"),
):
    """Configure the per-phone proxy."""
    phone = _manager().get(name)
    adb = Adb(phone.adb_address)
    adb.connect()
    spec = proxy_mod.ProxySpec.parse(url) if url else None
    console.print(proxy_mod.apply(adb, mode, spec))


@app.command()
def shell(name: str, cmd: str = typer.Argument(...)):
    """Run an adb shell command on a phone."""
    phone = _manager().get(name)
    adb = Adb(phone.adb_address)
    adb.connect()
    console.print(adb.shell(cmd, check=False))


@app.command()
def health():
    """Show health for all phones."""
    from . import health as health_mod

    mgr = _manager()
    table = Table("name", "container", "booted", "online", "cpu%", "mem MB", "SF", "crashes")
    for p in mgr.list():
        try:
            c = mgr.client.containers.get(p.name)
        except Exception:
            c = None
        h = health_mod.check(p, c)
        table.add_row(
            h.name,
            h.container_status,
            str(h.booted),
            str(h.online),
            str(h.cpu_pct),
            str(h.mem_mb),
            str(h.surfaceflinger),
            str(h.crashes_recent),
        )
    console.print(table)


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8080):
    """Start the web dashboard."""
    import uvicorn

    uvicorn.run("cloudphone.server:app", host=host, port=port, factory=False)


if __name__ == "__main__":
    app()
