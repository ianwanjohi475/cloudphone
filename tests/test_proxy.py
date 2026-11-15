"""The proxy bridge, tested against a small SOCKS5 server with a login.

    python3 -m unittest discover tests
"""

import asyncio
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
import proxy  # noqa: E402

USER, PASSWORD = "ian", "s3cret pass"


async def pipe(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except ConnectionError:
        pass
    finally:
        writer.close()


class Socks5Server:
    """Minimal SOCKS5 server that insists on USER/PASSWORD."""

    def __init__(self):
        self.targets = []

    async def start(self):
        self.server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def handle(self, r, w):
        try:
            _, count = await r.readexactly(2)
            methods = await r.readexactly(count)
            if 2 not in methods:
                w.write(b"\x05\xff")
                return w.close()
            w.write(b"\x05\x02")
            _, ulen = await r.readexactly(2)
            user = await r.readexactly(ulen)
            pw = await r.readexactly((await r.readexactly(1))[0])
            if (user.decode(), pw.decode()) != (USER, PASSWORD):
                w.write(b"\x01\x01")
                return w.close()
            w.write(b"\x01\x00")
            _, _, _, atyp = await r.readexactly(4)
            if atyp == 3:
                host = (await r.readexactly((await r.readexactly(1))[0])).decode()
            else:
                host = ".".join(map(str, await r.readexactly(4)))
            (port,) = struct.unpack(">H", await r.readexactly(2))
            self.targets.append((host, port))
            ur, uw = await asyncio.open_connection(host, port)
            w.write(b"\x05\x00\x00\x01" + bytes(6))
            await asyncio.gather(pipe(r, uw), pipe(ur, w))
        except (asyncio.IncompleteReadError, OSError):
            w.close()


async def web_handler(r, w):
    request = await r.readuntil(b"\r\n\r\n")
    body = b"saw: " + request.split(b"\r\n", 1)[0]
    w.write(b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))
    await w.drain()
    w.close()


class BridgeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.socks = Socks5Server()
        self.socks_port = await self.socks.start()
        self.web = await asyncio.start_server(web_handler, "127.0.0.1", 0)
        self.web_port = self.web.sockets[0].getsockname()[1]
        self.tmp = tempfile.TemporaryDirectory()
        self.bridge = proxy.Bridge(Path(self.tmp.name) / "proxy.json")
        await self.bridge.start("127.0.0.1", 0)

    async def asyncTearDown(self):
        await self.bridge.close()
        self.web.close()
        self.socks.server.close()
        self.tmp.cleanup()

    def config(self, password=PASSWORD):
        return proxy.ProxyConfig("socks5", "127.0.0.1", self.socks_port, USER, password)

    async def ask(self, request: bytes) -> bytes:
        r, w = await asyncio.open_connection("127.0.0.1", self.bridge.port)
        w.write(request)
        reply = await asyncio.wait_for(r.read(), 5)
        w.close()
        return reply

    async def connect_and_get(self) -> bytes:
        r, w = await asyncio.open_connection("127.0.0.1", self.bridge.port)
        w.write(b"CONNECT 127.0.0.1:%d HTTP/1.1\r\n\r\n" % self.web_port)
        status = await asyncio.wait_for(r.readuntil(b"\r\n\r\n"), 5)
        if b" 200 " not in status:
            w.close()
            return status
        w.write(b"GET /hello HTTP/1.1\r\nHost: x\r\n\r\n")
        reply = await asyncio.wait_for(r.read(), 5)
        w.close()
        return reply

    async def test_connect_goes_through_socks5_with_login(self):
        self.bridge.set(self.config())
        self.assertIn(b"saw: GET /hello HTTP/1.1", await self.connect_and_get())
        self.assertEqual(self.socks.targets, [("127.0.0.1", self.web_port)])

    async def test_plain_http_request_is_forwarded(self):
        self.bridge.set(self.config())
        reply = await self.ask(
            b"GET http://localhost:%d/page?q=1 HTTP/1.1\r\nHost: localhost\r\nProxy-Connection: keep-alive\r\n\r\n"
            % self.web_port
        )
        self.assertIn(b"saw: GET /page?q=1 HTTP/1.1", reply)
        self.assertEqual(self.socks.targets, [("localhost", self.web_port)])  # name resolved by the proxy

    async def test_wrong_password_fails_and_never_goes_direct(self):
        self.bridge.set(self.config(password="wrong"))
        self.assertIn(b"502", await self.connect_and_get())
        self.assertEqual(self.socks.targets, [])
        with self.assertRaisesRegex(proxy.ProxyError, "username or password"):
            await proxy.open_via(self.bridge.config, "127.0.0.1", self.web_port)

    async def test_proxy_down_fails_and_never_goes_direct(self):
        self.socks.server.close()
        await self.socks.server.wait_closed()
        self.bridge.set(self.config())
        self.assertIn(b"502", await self.connect_and_get())

    async def test_no_proxy_is_direct(self):
        self.assertIn(b"saw: GET /hello", await self.connect_and_get())
        self.assertEqual(self.socks.targets, [])

    async def test_config_is_saved_privately_and_reloaded(self):
        self.bridge.set(self.config())
        path = Path(self.tmp.name) / "proxy.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        again = proxy.Bridge(path)
        self.assertEqual(again.config, self.config())
        self.assertNotIn("password", again.config.public())
        self.assertTrue(again.config.public()["has_password"])


class UrlParsing(unittest.TestCase):
    def test_urls(self):
        c = proxy.ProxyConfig.from_url("socks5://ian:p%40ss@1.2.3.4:1080")
        self.assertEqual((c.type, c.host, c.port, c.username, c.password), ("socks5", "1.2.3.4", 1080, "ian", "p@ss"))
        self.assertEqual(proxy.ProxyConfig.from_url("host.example:9050").type, "socks5")
        self.assertEqual(proxy.ProxyConfig.from_url("http://h:3128").port, 3128)
        self.assertFalse(proxy.ProxyConfig.from_url("off").enabled)
        with self.assertRaises(proxy.ProxyError):
            proxy.ProxyConfig("socks5", "", 1080).validate()


if __name__ == "__main__":
    unittest.main()
