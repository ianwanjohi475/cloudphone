"""Proxy bridge: sends the phone's traffic through a SOCKS5 or HTTP proxy.

The Android emulator can only be pointed at a plain HTTP proxy without a
login. So the emulator is pointed at this bridge on 127.0.0.1, and the bridge
forwards every connection through the proxy the user configured (SOCKS5 with
username/password, or an HTTP proxy), or directly when none is set.

If the configured proxy is down, connections fail; they never fall back to the
direct route.
"""

from __future__ import annotations

import asyncio
import base64
import ipaddress
import json
import os
import re
import struct
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

TYPES = ("none", "socks5", "http")
TIMEOUT = 20
# Service that answers with the caller's public IP address (plain "host:port").
IP_CHECK = os.environ.get("CP_IP_CHECK", "api.ipify.org:80")
HOST_RE = re.compile(r"^[A-Za-z0-9._:-]{1,253}$")


class ProxyError(Exception):
    pass


@dataclass
class ProxyConfig:
    type: str = "none"
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""

    @property
    def enabled(self) -> bool:
        return self.type != "none"

    def public(self) -> dict:
        """What the web page may see: everything but the password."""
        d = asdict(self)
        d["has_password"] = bool(d.pop("password"))
        return d

    def validate(self) -> None:
        if self.type not in TYPES:
            raise ProxyError("type must be socks5, http or none")
        if not self.enabled:
            return
        if not HOST_RE.match(self.host):
            raise ProxyError("enter the proxy's host name or IP address")
        if not 1 <= self.port <= 65535:
            raise ProxyError("the port must be between 1 and 65535")
        if len(self.username.encode()) > 255 or len(self.password.encode()) > 255:
            raise ProxyError("username and password can be at most 255 bytes")

    @classmethod
    def from_url(cls, url: str) -> "ProxyConfig":
        """socks5://user:pass@host:port, http://host:port, or "off"."""
        if url.strip().lower() in ("", "off", "none"):
            return cls()
        if "://" not in url:
            url = "socks5://" + url
        parts = urlsplit(url)
        scheme = {"socks5h": "socks5", "socks": "socks5", "https": "http"}.get(parts.scheme, parts.scheme)
        try:
            port = parts.port or (1080 if scheme == "socks5" else 8080)
        except ValueError:
            raise ProxyError("the port is not a number") from None
        return cls(scheme, parts.hostname or "", port,
                   unquote(parts.username or ""), unquote(parts.password or ""))  # fmt: skip


async def _socks5(reader, writer, cfg: ProxyConfig, host: str, port: int) -> None:
    writer.write(b"\x05\x02\x00\x02" if cfg.username else b"\x05\x01\x00")
    version, method = await reader.readexactly(2)
    if version != 5:
        raise ProxyError("that is not a SOCKS5 proxy")
    if method == 2:
        user, pw = cfg.username.encode(), cfg.password.encode()
        writer.write(bytes([1, len(user)]) + user + bytes([len(pw)]) + pw)
        if (await reader.readexactly(2))[1] != 0:
            raise ProxyError("the proxy rejected the username or password")
    elif method != 0:
        raise ProxyError("the proxy needs a username and password" if not cfg.username
                         else "the proxy does not accept username/password logins")  # fmt: skip

    try:
        ip = ipaddress.ip_address(host)
        addr = bytes([1 if ip.version == 4 else 4]) + ip.packed
    except ValueError:
        name = host.encode("idna")
        addr = bytes([3, len(name)]) + name
    writer.write(b"\x05\x01\x00" + addr + struct.pack(">H", port))
    _, reply, _, atyp = await reader.readexactly(4)
    if reply != 0:
        reasons = {1: "general failure", 2: "not allowed", 3: "network unreachable",
                   4: "host unreachable", 5: "connection refused", 6: "timed out"}  # fmt: skip
        raise ProxyError(f"the proxy could not connect ({reasons.get(reply, f'code {reply}')})")
    size = {1: 4, 4: 16}.get(atyp)
    if size is None:
        size = (await reader.readexactly(1))[0]
    await reader.readexactly(size + 2)


async def _http_connect(reader, writer, cfg: ProxyConfig, host: str, port: int) -> None:
    target = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    head = f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n"
    if cfg.username:
        token = base64.b64encode(f"{cfg.username}:{cfg.password}".encode()).decode()
        head += f"Proxy-Authorization: Basic {token}\r\n"
    writer.write((head + "\r\n").encode())
    reply = await reader.readuntil(b"\r\n\r\n")
    status = reply.split(b" ", 2)[1:2]
    if status == [b"407"]:
        raise ProxyError("the proxy rejected the username or password")
    if status != [b"200"]:
        raise ProxyError("the proxy refused: " + reply.split(b"\r\n", 1)[0].decode(errors="replace"))


async def open_via(cfg: ProxyConfig, host: str, port: int):
    """Open a connection to host:port through cfg. Returns (reader, writer)."""
    if not cfg.enabled:
        return await asyncio.wait_for(asyncio.open_connection(host, port), TIMEOUT)
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(cfg.host, cfg.port), TIMEOUT)
    except (OSError, asyncio.TimeoutError):
        raise ProxyError(f"cannot reach the proxy at {cfg.host}:{cfg.port}") from None
    try:
        handshake = _socks5 if cfg.type == "socks5" else _http_connect
        await asyncio.wait_for(handshake(reader, writer, cfg, host, port), TIMEOUT)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
        writer.close()
        raise ProxyError("the proxy closed the connection (wrong type or port?)") from None
    except asyncio.TimeoutError:
        writer.close()
        raise ProxyError("the proxy did not answer in time") from None
    except BaseException:
        writer.close()
        raise
    return reader, writer


async def exit_ip(cfg: ProxyConfig) -> str:
    """The public IP address websites see through cfg."""
    host, _, port = IP_CHECK.partition(":")
    reader, writer = await open_via(cfg, host, int(port or 80))
    try:
        writer.write(f"GET / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
        reply = await asyncio.wait_for(reader.read(4096), TIMEOUT)
        while b"\r\n\r\n" not in reply and (more := await asyncio.wait_for(reader.read(4096), TIMEOUT)):
            reply += more
    except (asyncio.TimeoutError, ConnectionError):
        raise ProxyError("connected, but no reply came back through the proxy") from None
    finally:
        writer.close()
    body = reply.split(b"\r\n\r\n", 1)[-1].strip().decode(errors="replace")
    try:
        return str(ipaddress.ip_address(body.split()[-1] if body else ""))
    except (ValueError, IndexError):
        raise ProxyError("connected, but could not read the public IP address") from None


async def _copy(reader, writer) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
        if writer.can_write_eof():
            writer.write_eof()
    except (ConnectionError, OSError):
        pass


class Bridge:
    """Local HTTP proxy (CONNECT and plain requests) in front of the config."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.config = ProxyConfig()
        self._writers: set[asyncio.StreamWriter] = set()
        self._server: asyncio.AbstractServer | None = None
        if path and path.is_file():
            try:
                self.config = ProxyConfig(**json.loads(path.read_text()))
                self.config.validate()
            except (ValueError, TypeError, ProxyError):
                self.config = ProxyConfig()

    def set(self, cfg: ProxyConfig) -> None:
        cfg.validate()
        self.config = cfg
        if self.path:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(asdict(cfg), f)
        # Drop open connections so apps reconnect over the new route.
        for w in list(self._writers):
            w.close()

    async def start(self, host: str, port: int) -> None:
        self._server = await asyncio.start_server(self._handle, host, port)

    @property
    def port(self) -> int:
        return self._server.sockets[0].getsockname()[1] if self._server else 0

    async def close(self) -> None:
        if self._server:
            self._server.close()
        for w in list(self._writers):
            w.close()

    async def _handle(self, reader, writer) -> None:
        upstream = None
        self._writers.add(writer)
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 30)
            first, _, rest = head.partition(b"\r\n")
            method, target, version = first.decode("latin-1").split(" ", 2)

            if method.upper() == "CONNECT":
                host, _, port = target.rpartition(":")
                send = b""
            else:  # plain "GET http://host/path": forward it as a normal request
                url = urlsplit(target)
                if url.scheme != "http" or not url.hostname:
                    raise ProxyError("unsupported request")
                host, port = url.hostname, str(url.port or 80)
                path = (url.path or "/") + (f"?{url.query}" if url.query else "")
                lines = [ln for ln in rest.split(b"\r\n") if not ln.lower().startswith(b"proxy-")]
                send = f"{method} {path} {version}\r\n".encode("latin-1") + b"\r\n".join(lines)

            try:
                upstream, up_writer = await open_via(self.config, host.strip("[]"), int(port))
            except (ProxyError, OSError, asyncio.TimeoutError) as e:
                writer.write(f"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n{e}\n".encode())
                return
            self._writers.add(up_writer)
            if send:
                up_writer.write(send)
            else:
                writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            try:
                await asyncio.gather(_copy(reader, up_writer), _copy(upstream, writer))
            finally:
                self._writers.discard(up_writer)
                up_writer.close()
        except (ProxyError, ValueError, asyncio.IncompleteReadError, asyncio.LimitOverrunError,
                asyncio.TimeoutError, ConnectionError, OSError):  # fmt: skip
            pass
        finally:
            self._writers.discard(writer)
            writer.close()
