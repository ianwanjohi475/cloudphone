import pytest

from cloudphone.proxy import ProxySpec, apply


class FakeAdb:
    def __init__(self):
        self.cmds = []

    def shell(self, cmd, check=True):
        self.cmds.append(cmd)
        return ""


def test_parse_socks5_with_auth():
    s = ProxySpec.parse("socks5://user:pass@host.example:1080")
    assert (s.scheme, s.host, s.port, s.user, s.password) == (
        "socks5",
        "host.example",
        1080,
        "user",
        "pass",
    )


def test_parse_http_no_auth():
    s = ProxySpec.parse("http://1.2.3.4:8080")
    assert (s.scheme, s.host, s.port) == ("http", "1.2.3.4", 8080)
    assert s.user == "" and s.password == ""


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        ProxySpec.parse("ftp://nope")


def test_apply_http_sets_global_proxy():
    adb = FakeAdb()
    msg = apply(adb, "http", ProxySpec.parse("http://1.2.3.4:8080"))
    assert any("settings put global http_proxy 1.2.3.4:8080" in c for c in adb.cmds)
    assert "1.2.3.4:8080" in msg


def test_apply_transparent_uses_iptables_and_redsocks():
    adb = FakeAdb()
    apply(adb, "transparent", ProxySpec.parse("socks5://h:1080"))
    joined = "\n".join(adb.cmds)
    assert "redsocks" in joined
    assert "REDIRECT --to-ports 12345" in joined


def test_apply_off_clears():
    adb = FakeAdb()
    msg = apply(adb, "off", None)
    assert "disabled" in msg
    assert any("http_proxy :0" in c for c in adb.cmds)


def test_apply_browser_writes_chrome_flag():
    adb = FakeAdb()
    apply(adb, "browser", ProxySpec.parse("http://1.2.3.4:8080"))
    assert any("chrome-command-line" in c for c in adb.cmds)
