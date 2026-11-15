#!/usr/bin/env python3
"""cloudphone server: puts an Android phone in a browser tab.

It talks to one Android device over adb and serves a web page that shows the
screen and takes touch / keyboard input.

  screen   scrcpy's server runs on the phone and produces H.264; we relay the
           frames over a WebSocket and the browser decodes them (WebCodecs).
           If that cannot start, we fall back to sending screenshots.
  input    scrcpy's control channel (fast, multi-touch), or `adb shell input`
           in screenshot mode.
  apps     upload an .apk / .xapk / .apks / .apkm / .zip and it is installed.

Configuration is by environment variable, set by the `cloudphone` launcher:
  CP_ADB, CP_SERIAL, CP_HOST, CP_PORT, CP_TOKEN, CP_SCRCPY_JAR,
  CP_MAX_SIZE, CP_BITRATE, CP_FPS,
  CP_STATE (folder for saved settings), CP_BRIDGE_PORT (proxy bridge port),
  CP_LAUNCHER (path of the `cloudphone` script, used to restart the phone)
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import re
import secrets
import shlex
import shutil
import socket
import struct
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from aiohttp import WSMsgType, web

import proxy as proxy_mod

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"

ADB = os.environ.get("CP_ADB") or shutil.which("adb") or "adb"
SERIAL = os.environ.get("CP_SERIAL", "emulator-5554")
HOST = os.environ.get("CP_HOST", "127.0.0.1")
PORT = int(os.environ.get("CP_PORT", "8080"))
TOKEN = os.environ.get("CP_TOKEN", "")
SCRCPY_JAR = Path(os.environ.get("CP_SCRCPY_JAR", HERE / "scrcpy-server.jar"))
SCRCPY_VERSION = os.environ.get("CP_SCRCPY_VERSION", "2.7")
MAX_SIZE = int(os.environ.get("CP_MAX_SIZE", "1280"))
BITRATE = int(os.environ.get("CP_BITRATE", "4000000"))
FPS = int(os.environ.get("CP_FPS", "30"))

STATE_DIR = Path(os.environ["CP_STATE"]) if os.environ.get("CP_STATE") else None
BRIDGE_PORT = int(os.environ.get("CP_BRIDGE_PORT", "0"))
LAUNCHER = os.environ.get("CP_LAUNCHER", "")
bridge = proxy_mod.Bridge(STATE_DIR / "proxy.json" if STATE_DIR else None)

REMOTE_JAR = "/data/local/tmp/cloudphone-scrcpy.jar"
COOKIE = "cp_key"

# Packet types sent to the browser (first byte of every binary message).
PKT_CONFIG, PKT_KEY, PKT_DELTA, PKT_IMAGE = 0, 1, 2, 9

# Android constants
ACTION_DOWN, ACTION_UP, ACTION_MOVE = 0, 1, 2
PACKAGE_RE = re.compile(r"^[A-Za-z][\w]*(\.[A-Za-z_][\w]*)+$")
ABI_RE = re.compile(r"(arm64_v8a|armeabi_v7a|armeabi|x86_64|x86)")


# --------------------------------------------------------------------- adb
async def adb(*args: str, timeout: float = 30, merge: bool = True) -> tuple[int, bytes]:
    """Run `adb -s SERIAL args…`. Returns (exit code, output)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            ADB,
            "-s",
            SERIAL,
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT if merge else asyncio.subprocess.DEVNULL,
        )
    except OSError as e:
        return 127, str(e).encode()
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, b"timed out"
    return proc.returncode or 0, out


async def shell(cmd: str, timeout: float = 30) -> tuple[int, bytes]:
    return await adb("shell", cmd, timeout=timeout)


_state = {"at": 0.0, "value": "offline", "prepared": False, "jar": False}


async def device_state() -> str:
    """offline (no device) | booting | ready. Cached for a second."""
    now = time.monotonic()
    if now - _state["at"] < 1.0:
        return _state["value"]
    value = "offline"
    code, out = await adb("get-state", timeout=5)
    if code == 0 and out.strip() == b"device":
        code, out = await shell("getprop sys.boot_completed", timeout=5)
        value = "ready" if out.strip() == b"1" else "booting"
    if value != "ready":
        _state["prepared"] = _state["jar"] = False
    elif not _state["prepared"]:
        _state["prepared"] = True
        await prepare_device()
    _state["at"], _state["value"] = time.monotonic(), value
    return value


async def prepare_device() -> None:
    """One-time comfort settings after each boot: keep the screen on, no lock."""
    await shell(
        "svc power stayon true;"
        "settings put system screen_off_timeout 2147483647;"
        "locksettings set-disabled true;"
        "settings put global window_animation_scale 0.5;"
        "settings put global transition_animation_scale 0.5;"
        "input keyevent 224;"  # WAKEUP
        "wm dismiss-keyguard"
    )


# ------------------------------------------------------------------ scrcpy
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def pack_touch(action: int, pointer: int, x: int, y: int, w: int, h: int) -> bytes:
    pressure = 0 if action == ACTION_UP else 0xFFFF
    return struct.pack(">BBqiiHHHii", 2, action, pointer, x, y, w, h, pressure, 0, 0)


def pack_key(action: int, keycode: int, meta: int = 0) -> bytes:
    return struct.pack(">BBiii", 0, action, keycode, 0, meta)


def pack_text(text: str) -> bytes:
    data = text.encode()
    return struct.pack(">BI", 1, len(data)) + data


def pack_scroll(x: int, y: int, w: int, h: int, dx: int, dy: int) -> bytes:
    def fp(v: int) -> int:  # -1..1 as 16-bit fixed point
        return 0x7FFF if v > 0 else (-0x8000 if v < 0 else 0)

    return struct.pack(">BiiHHhhi", 3, x, y, w, h, fp(dx), fp(dy), 0)


class ScrcpySession:
    """One scrcpy server on the phone: an H.264 stream and a control channel."""

    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self.port = 0
        self.video: asyncio.StreamReader | None = None
        self._writers: list[asyncio.StreamWriter] = []
        self._control: asyncio.StreamWriter | None = None
        self._tasks: list[asyncio.Task] = []
        self.log: list[str] = []

    async def start(self) -> None:
        if not SCRCPY_JAR.is_file():
            raise RuntimeError(f"{SCRCPY_JAR} is missing")
        if not _state["jar"]:
            code, out = await adb("push", str(SCRCPY_JAR), REMOTE_JAR, timeout=60)
            if code != 0:
                raise RuntimeError(f"could not copy the screen streamer: {out.decode(errors='replace')}")
            _state["jar"] = True

        scid = f"{secrets.randbelow(1 << 31):08x}"
        self.port = _free_port()
        code, out = await adb("forward", f"tcp:{self.port}", f"localabstract:scrcpy_{scid}")
        if code != 0:
            raise RuntimeError(f"adb forward failed: {out.decode(errors='replace')}")

        self.proc = await asyncio.create_subprocess_exec(
            ADB, "-s", SERIAL, "shell",
            f"CLASSPATH={REMOTE_JAR}", "app_process", "/", "com.genymobile.scrcpy.Server",
            SCRCPY_VERSION, f"scid={scid}", "log_level=info",
            "tunnel_forward=true", "audio=false", "control=true", "cleanup=false",
            f"max_size={MAX_SIZE}", f"video_bit_rate={BITRATE}", f"max_fps={FPS}",
            "send_device_meta=false", "send_codec_meta=false",
            "send_frame_meta=true", "send_dummy_byte=true",
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )  # fmt: skip
        self._tasks.append(asyncio.create_task(self._read_log()))

        # The server needs a moment to start listening. Until then adb accepts
        # our connection and drops it; once it is up it greets with one 0 byte.
        deadline = time.monotonic() + 20
        while True:
            if self.proc.returncode is not None:
                raise RuntimeError("screen streamer exited: " + " | ".join(self.log[-5:]))
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
                first = await asyncio.wait_for(reader.read(1), 15)
                if first == b"\x00":
                    break
                writer.close()
            except (OSError, asyncio.TimeoutError):
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("screen streamer did not start: " + " | ".join(self.log[-5:]))
            await asyncio.sleep(0.25)
        self.video = reader
        self._writers.append(writer)

        creader, self._control = await asyncio.open_connection("127.0.0.1", self.port)
        self._writers.append(self._control)
        self._tasks.append(asyncio.create_task(self._drain(creader)))

    async def _read_log(self) -> None:
        assert self.proc and self.proc.stdout
        async for line in self.proc.stdout:
            self.log.append(line.decode(errors="replace").strip())
            del self.log[:-50]

    @staticmethod
    async def _drain(reader: asyncio.StreamReader) -> None:
        # The phone sends clipboard updates here; we do not use them.
        while await reader.read(65536):
            pass

    async def packets(self):
        """Yield (type, data) for every encoded video packet."""
        assert self.video
        while True:
            try:
                header = await self.video.readexactly(12)
                pts, size = struct.unpack(">QI", header)
                data = await self.video.readexactly(size)
            except (asyncio.IncompleteReadError, ConnectionError):
                return
            if pts >> 63:
                yield PKT_CONFIG, data
            elif (pts >> 62) & 1:
                yield PKT_KEY, data
            else:
                yield PKT_DELTA, data

    def _send(self, data: bytes) -> None:
        if self._control and not self._control.is_closing():
            self._control.write(data)

    # input interface (same as AdbInput)
    async def touch(self, action: int, pointer: int, x: int, y: int, w: int, h: int) -> None:
        self._send(pack_touch(action, pointer, x, y, w, h))

    async def key(self, keycode: int, meta: int = 0) -> None:
        self._send(pack_key(ACTION_DOWN, keycode, meta) + pack_key(ACTION_UP, keycode, meta))

    async def text(self, text: str) -> None:
        for i in range(0, len(text), 60):  # scrcpy caps one message at 300 bytes
            self._send(pack_text(text[i : i + 60]))

    async def scroll(self, x: int, y: int, w: int, h: int, dx: int, dy: int) -> None:
        self._send(pack_scroll(x, y, w, h, dx, dy))

    async def rotate(self) -> None:
        self._send(bytes([11]))

    async def close(self) -> None:
        for t in self._tasks:
            t.cancel()
        for w in self._writers:
            w.close()
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass
        if self.port:
            await adb("forward", "--remove", f"tcp:{self.port}", timeout=5)


class AdbInput:
    """Input through `adb shell input`: slower, single touch, always works."""

    def __init__(self) -> None:
        self._down: tuple[int, int, float] | None = None
        self._last = (0, 0)

    async def touch(self, action: int, pointer: int, x: int, y: int, w: int, h: int) -> None:
        if action == ACTION_DOWN:
            self._down = (x, y, time.monotonic())
        elif action == ACTION_MOVE:
            self._last = (x, y)
        elif action == ACTION_UP and self._down:
            x0, y0, t0 = self._down
            self._down = None
            ms = int((time.monotonic() - t0) * 1000)
            if abs(x - x0) + abs(y - y0) < 16:
                if ms > 600:
                    await shell(f"input swipe {x0} {y0} {x0} {y0} {ms}")  # long press
                else:
                    await shell(f"input tap {x0} {y0}")
            else:
                await shell(f"input swipe {x0} {y0} {x} {y} {max(80, min(ms, 2000))}")

    async def key(self, keycode: int, meta: int = 0) -> None:
        await shell(f"input keyevent {keycode}")

    async def text(self, text: str) -> None:
        # `input text` wants %s for spaces; quote the rest for the device shell.
        quoted = "'" + text.replace("'", "'\\''").replace(" ", "%s") + "'"
        await shell(f"input text {quoted}")

    async def scroll(self, x: int, y: int, w: int, h: int, dx: int, dy: int) -> None:
        step = h // 4
        x2 = max(0, min(w, x + dx * step))
        y2 = max(0, min(h, y + dy * step))
        await shell(f"input swipe {x} {y} {x2} {y2} 150")

    async def rotate(self) -> None:
        _, out = await shell("settings get system user_rotation")
        current = int(out.strip() or 0) if out.strip().isdigit() else 0
        await shell(
            "settings put system accelerometer_rotation 0;"
            f"settings put system user_rotation {(current + 1) % 4}"
        )


# --------------------------------------------------------------- websocket
def _int(msg: dict, key: str, lo: int = -(1 << 31), hi: int = (1 << 31) - 1) -> int:
    return max(lo, min(hi, int(msg.get(key, 0))))


async def handle_input(inp, msg: dict) -> None:
    kind = msg.get("t")
    if kind == "touch":
        action = _int(msg, "a", 0, 2)
        w, h = _int(msg, "w", 1, 0xFFFF), _int(msg, "h", 1, 0xFFFF)
        x, y = _int(msg, "x", 0, w), _int(msg, "y", 0, h)
        await inp.touch(action, _int(msg, "id", 0, 9), x, y, w, h)
    elif kind == "key":
        await inp.key(_int(msg, "k", 0, 1000), _int(msg, "m", 0, 0xFFFFFF))
    elif kind == "text":
        text = str(msg.get("s", ""))[:2000]
        if text:
            await inp.text(text)
    elif kind == "scroll":
        w, h = _int(msg, "w", 1, 0xFFFF), _int(msg, "h", 1, 0xFFFF)
        await inp.scroll(_int(msg, "x", 0, w), _int(msg, "y", 0, h), w, h,
                         _int(msg, "dx", -1, 1), _int(msg, "dy", -1, 1))  # fmt: skip
    elif kind == "rotate":
        await inp.rotate()


async def pump_video(ws: web.WebSocketResponse, session: ScrcpySession) -> None:
    async for kind, data in session.packets():
        await ws.send_bytes(bytes([kind]) + data)


async def pump_screenshots(ws: web.WebSocketResponse) -> None:
    previous = b""
    while True:
        code, png = await adb("exec-out", "screencap", "-p", timeout=15, merge=False)
        if code == 0 and png.startswith(b"\x89PNG"):
            if png != previous:
                await ws.send_bytes(bytes([PKT_IMAGE]) + png)
                previous = png
        elif await device_state() != "ready":
            return
        await asyncio.sleep(0.15)


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=1 << 20)
    await ws.prepare(request)

    session: ScrcpySession | None = None
    if request.query.get("mode") != "shot":
        session = ScrcpySession()
        try:
            await session.start()
        except Exception as e:  # any failure -> screenshots still work
            await session.close()
            session = None
            await ws.send_json({"t": "fallback", "reason": str(e)[:300]})

    if session:
        inp = session
        pump = asyncio.create_task(pump_video(ws, session))
        await ws.send_json({"t": "mode", "mode": "video"})
    else:
        inp = AdbInput()
        pump = asyncio.create_task(pump_screenshots(ws))
        await ws.send_json({"t": "mode", "mode": "shot"})
    # If the stream ends (phone rebooted…), close so the browser reconnects.
    pump.add_done_callback(lambda _: asyncio.ensure_future(ws.close()))

    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                await handle_input(inp, json.loads(msg.data))
            except (ValueError, TypeError, AttributeError):
                pass
    finally:
        pump.cancel()
        if session:
            await session.close()
    return ws


# ------------------------------------------------------------ installing
def pick_apks(names: list[str], device_abis: list[str]) -> list[str]:
    """From the .apk files of a bundle, drop splits built for CPU types the
    phone cannot use, keeping the phone's most preferred one."""
    by_abi: dict[str, list[str]] = {}
    plain: list[str] = []
    for name in names:
        m = ABI_RE.search(Path(name).stem.replace("-", "_")) if "config" in Path(name).name.lower() else None
        (by_abi.setdefault(m.group(1), []) if m else plain).append(name)
    if not by_abi:
        return plain
    for abi in (a.replace("-", "_") for a in device_abis):
        if abi in by_abi:
            return plain + by_abi[abi]
    raise ValueError(
        f"this app is built for {', '.join(sorted(by_abi))}; the phone runs {', '.join(device_abis)}"
    )


async def install_file(path: Path) -> str:
    """Install an .apk or a bundle. Returns the package manager's last line."""
    if path.suffix.lower() == ".apk":
        code, out = await adb("install", "-r", str(path), timeout=900)
    else:
        if not zipfile.is_zipfile(path):
            raise ValueError("not an .apk or an app bundle (.xapk, .apks, .apkm, .zip)")
        with tempfile.TemporaryDirectory(prefix="cloudphone-") as tmp:
            with zipfile.ZipFile(path) as z:
                z.extractall(tmp)
            root = Path(tmp)
            apks = sorted(str(p) for p in root.rglob("*.apk"))
            if not apks:
                raise ValueError("no .apk files inside this bundle")
            _, abis = await shell("getprop ro.product.cpu.abilist")
            chosen = pick_apks(apks, [a for a in abis.decode().strip().split(",") if a])
            code, out = await adb("install-multiple", "-r", *chosen, timeout=900)
            if code == 0 and b"Success" in out:
                for obb in root.rglob("*.obb"):  # game data
                    target = f"/sdcard/Android/obb/{obb.parent.name}/{obb.name}"
                    await shell(f"mkdir -p '/sdcard/Android/obb/{obb.parent.name}'")
                    await adb("push", str(obb), target, timeout=900)
    text = out.decode(errors="replace").strip()
    if code != 0 or "Success" not in text:
        raise ValueError(text.splitlines()[-1] if text else "install failed")
    return "Installed"


async def api_install(request: web.Request) -> web.Response:
    if await device_state() != "ready":
        return web.json_response({"ok": False, "error": "the phone is not ready yet"}, status=409)
    reader = await request.multipart()
    part = await reader.next()
    while part is not None and part.name != "file":
        part = await reader.next()
    if part is None or not part.filename:
        return web.json_response({"ok": False, "error": "no file"}, status=400)
    suffix = Path(part.filename).suffix.lower()
    with tempfile.TemporaryDirectory(prefix="cloudphone-up-") as tmp:
        if not re.fullmatch(r"\.[a-z0-9]{1,5}", suffix):
            suffix = ".zip"
        dest = Path(tmp) / ("upload" + suffix)
        with dest.open("wb") as f:
            while chunk := await part.read_chunk(1 << 20):
                f.write(chunk)
        try:
            message = await install_file(dest)
        except (ValueError, zipfile.BadZipFile, OSError) as e:
            return web.json_response({"ok": False, "error": str(e)}, status=422)
    return web.json_response({"ok": True, "message": message})


# ------------------------------------------------------------------ files
FILES_DIR = "/sdcard/Download"  # shows up as "Downloads" in the phone's Files app


def safe_name(name: str) -> str:
    """A file name that is safe to put in the phone's Downloads folder."""
    name = re.sub(r"[^\w .()\-]+", "_", Path(name.replace("\\", "/")).name).strip(" .")
    stem, dot, ext = name.rpartition(".")
    return (f"{stem[:100]}.{ext[:12]}" if dot and stem else name[:112]) or "file"


async def api_files_list(request: web.Request) -> web.Response:
    if await device_state() != "ready":
        return web.json_response({"files": [], "error": "the phone is not ready yet"}, status=409)
    _, out = await shell(f"cd {FILES_DIR} 2>/dev/null && stat -c '%F|%s|%Y|%n' -- * 2>/dev/null")
    files = []
    for line in out.decode(errors="replace").splitlines():
        kind, _, rest = line.partition("|")
        size, _, rest = rest.partition("|")
        mtime, _, name = rest.partition("|")
        if kind == "regular file" and size.isdigit() and mtime.isdigit():
            files.append({"name": name, "size": int(size), "mtime": int(mtime)})
    files.sort(key=lambda f: -f["mtime"])
    return web.json_response({"files": files, "folder": "Downloads"})


async def api_files_upload(request: web.Request) -> web.Response:
    """Copy uploaded files (any type) into the phone's Downloads folder."""
    if await device_state() != "ready":
        return web.json_response({"ok": False, "error": "the phone is not ready yet"}, status=409)
    saved, reader = [], await request.multipart()
    await shell(f"mkdir -p {FILES_DIR}")
    with tempfile.TemporaryDirectory(prefix="cloudphone-file-") as tmp:
        while (part := await reader.next()) is not None:
            if part.name != "file" or not part.filename:
                continue
            name = safe_name(part.filename)
            local = Path(tmp) / "upload"
            with local.open("wb") as f:
                while chunk := await part.read_chunk(1 << 20):
                    f.write(chunk)
            target = f"{FILES_DIR}/{name}"
            code, out = await adb("push", str(local), target, timeout=3600)
            if code != 0:
                text = out.decode(errors="replace").strip().splitlines()
                error = text[-1] if text else "copy failed"
                return web.json_response({"ok": False, "error": f"{name}: {error}", "saved": saved}, status=422)
            # Tell the gallery / Files app about it (harmless if unsupported).
            await shell(f"content call --uri content://media --method scan_file --arg {shlex.quote(target)}")
            saved.append(name)
    if not saved:
        return web.json_response({"ok": False, "error": "no file"}, status=400)
    return web.json_response({"ok": True, "saved": saved, "folder": "Downloads"})


async def api_files_delete(request: web.Request) -> web.Response:
    name = request.query.get("name", "")
    if not name or "/" in name or name in (".", "..") or "\x00" in name:
        return web.json_response({"ok": False, "error": "bad file name"}, status=400)
    target = shlex.quote(f"{FILES_DIR}/{name}")
    code, _ = await shell(f"rm -f -- {target} && [ ! -e {target} ]")
    return web.json_response({"ok": code == 0}, status=200 if code == 0 else 500)


# -------------------------------------------------------------------- api
async def api_status(request: web.Request) -> web.Response:
    return web.json_response({"state": await device_state()})


async def api_launch(request: web.Request) -> web.Response:
    try:
        package = str((await request.json()).get("package", ""))
    except ValueError:
        package = ""
    if not PACKAGE_RE.match(package):
        return web.json_response({"ok": False, "error": "bad package name"}, status=400)
    code, out = await shell(f"monkey -p {package} -c android.intent.category.LAUNCHER 1")
    ok = code == 0 and b"No activities found" not in out
    return web.json_response({"ok": ok}, status=200 if ok else 404)


# ------------------------------------------------------------------ proxy
def _phone_uses_bridge() -> bool:
    """Whether the running phone was started pointing at the proxy bridge
    (the launcher records this when it powers the phone on)."""
    try:
        return (STATE_DIR / "run" / "emulator.bridged").read_text().strip() == "1"
    except (OSError, TypeError):
        return False


def _proxy_state() -> dict:
    cfg = bridge.config
    return {**cfg.public(), "needs_restart": cfg.enabled != _phone_uses_bridge()}


async def api_proxy_get(request: web.Request) -> web.Response:
    return web.json_response(_proxy_state())


async def api_proxy_set(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        if "url" in body:
            cfg = proxy_mod.ProxyConfig.from_url(str(body["url"]))
        else:
            old = bridge.config
            cfg = proxy_mod.ProxyConfig(
                type=str(body.get("type", "none")),
                host=str(body.get("host", "")).strip(),
                port=int(body.get("port") or 0),
                username=str(body.get("username", "")),
                # The page never receives the saved password; leaving the
                # field empty means "keep it".
                password=str(body["password"]) if "password" in body else old.password,
            )
        cfg.validate()
        ip = await proxy_mod.exit_ip(cfg) if cfg.enabled else ""
    except proxy_mod.ProxyError as e:
        return web.json_response({"ok": False, "error": str(e)}, status=422)
    except (ValueError, TypeError, AttributeError):
        return web.json_response({"ok": False, "error": "bad request"}, status=400)

    bridge.set(cfg)
    restarting = False
    if STATE_DIR:
        marker = STATE_DIR / "proxy.on"
        marker.touch() if cfg.enabled else marker.unlink(missing_ok=True)
        # The phone only learns about the bridge when it powers on, so going
        # from "no proxy" to "proxy" (or back) restarts it. Changing from one
        # proxy to another applies immediately.
        if LAUNCHER and cfg.enabled != _phone_uses_bridge():
            await asyncio.create_subprocess_exec(
                LAUNCHER, "reboot",
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
            )  # fmt: skip
            restarting = True
    return web.json_response({"ok": True, "ip": ip, "restarting": restarting, **cfg.public()})


async def _start_bridge(app: web.Application) -> None:
    if BRIDGE_PORT:
        await bridge.start("127.0.0.1", BRIDGE_PORT)


async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


LOGIN_PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>cloudphone</title><body style="font:16px system-ui;background:#0f1115;color:#e8eaf0;display:grid;place-items:center;height:100vh;margin:0">
<form method=get action=/ style="display:grid;gap:12px;width:min(320px,90vw)"><b>cloudphone</b>
<label>Access key<br><input name=key type=password autofocus style="width:100%;padding:10px;box-sizing:border-box;font:inherit"></label>
<button style="padding:10px;font:inherit">Open phone</button>
<small style="opacity:.7">The key is printed by <code>./cloudphone link</code>.</small></form>"""


@web.middleware
async def auth(request: web.Request, handler):
    # Requests from another website must not drive the phone.
    origin = request.headers.get("Origin")
    if origin and urlsplit(origin).netloc != request.host:
        return web.Response(status=403, text="cross-origin request refused")
    if not TOKEN:
        return await handler(request)
    key = request.query.get("key")
    if key is not None and request.path == "/":
        if hmac.compare_digest(key.encode(), TOKEN.encode()):
            resp = web.HTTPFound("/")
            resp.set_cookie(COOKIE, TOKEN, httponly=True, samesite="Lax", max_age=30 * 86400)
            return resp
    elif hmac.compare_digest(request.cookies.get(COOKIE, "").encode(), TOKEN.encode()):
        return await handler(request)
    if request.path == "/":
        return web.Response(status=401, text=LOGIN_PAGE, content_type="text/html")
    return web.Response(status=401, text="access key required")


def make_app() -> web.Application:
    app = web.Application(middlewares=[auth])
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/api/status", api_status)
    app.router.add_post("/api/install", api_install)
    app.router.add_post("/api/launch", api_launch)
    app.router.add_get("/api/files", api_files_list)
    app.router.add_post("/api/files", api_files_upload)
    app.router.add_delete("/api/files", api_files_delete)
    app.router.add_get("/api/proxy", api_proxy_get)
    app.router.add_post("/api/proxy", api_proxy_set)
    app.on_startup.append(_start_bridge)
    app.router.add_static("/static", STATIC)
    return app


if __name__ == "__main__":
    web.run_app(make_app(), host=HOST, port=PORT, print=None)
