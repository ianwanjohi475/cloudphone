"""Per-phone proxy engine.

Four modes:
  - http        : set Android global http_proxy (system-wide, app-respecting)
  - socks5      : route all TCP through SOCKS5 via redsocks (transparent at TCP)
  - transparent : iptables redirect of all egress into redsocks (no app config)
  - browser     : only configure the browser/WebView, leave the rest direct

`socks5` and `transparent` require root in the phone (Magisk). `http` and
`browser` work without root.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .adb import Adb


@dataclass
class ProxySpec:
    scheme: str  # http | socks5
    host: str
    port: int
    user: str = ""
    password: str = ""

    @classmethod
    def parse(cls, url: str) -> "ProxySpec":
        # socks5://user:pass@host:port  or  http://host:port
        m = re.match(
            r"^(?P<scheme>socks5|http)://"
            r"(?:(?P<user>[^:@]+):(?P<pw>[^@]*)@)?"
            r"(?P<host>[^:/]+):(?P<port>\d+)/?$",
            url.strip(),
        )
        if not m:
            raise ValueError(f"bad proxy url: {url!r}")
        return cls(
            scheme=m["scheme"],
            host=m["host"],
            port=int(m["port"]),
            user=m["user"] or "",
            password=m["pw"] or "",
        )


REDSOCKS_CONF = """\
base {{
    log_debug = off;
    log_info = on;
    daemon = on;
    redirector = iptables;
}}
redsocks {{
    local_ip = 127.0.0.1;
    local_port = 12345;
    ip = {host};
    port = {port};
    type = {rtype};
    {auth}
}}
"""


def apply(adb: Adb, mode: str, spec: ProxySpec | None) -> str:
    """Configure proxy `mode` on the phone. Returns a human status string."""
    if mode == "off" or spec is None:
        adb.shell("settings put global http_proxy :0", check=False)
        adb.shell("su -c 'iptables -t nat -F OUTPUT' 2>/dev/null || true", check=False)
        return "proxy disabled"

    if mode == "http":
        adb.shell(f"settings put global http_proxy {spec.host}:{spec.port}", check=False)
        return f"http_proxy -> {spec.host}:{spec.port}"

    if mode == "browser":
        # Browser-only: write a chrome command line flag; leave system direct.
        adb.shell(
            "echo 'chrome --proxy-server={s}://{h}:{p}' > /data/local/tmp/chrome-command-line".format(
                s=spec.scheme, h=spec.host, p=spec.port
            ),
            check=False,
        )
        adb.shell("settings put global http_proxy :0", check=False)
        return f"browser proxy -> {spec.scheme}://{spec.host}:{spec.port}"

    if mode in ("socks5", "transparent"):
        rtype = "socks5" if spec.scheme == "socks5" else "http-connect"
        auth = f'login = "{spec.user}";\n    password = "{spec.password}";' if spec.user else ""
        conf = REDSOCKS_CONF.format(host=spec.host, port=spec.port, rtype=rtype, auth=auth)
        adb.shell(
            f"su -c 'cat > /data/local/tmp/redsocks.conf <<\"EOF\"\n{conf}\nEOF'", check=False
        )
        adb.shell(
            "su -c 'pkill redsocks 2>/dev/null; redsocks -c /data/local/tmp/redsocks.conf'",
            check=False,
        )
        # Redirect all outbound TCP (except to the proxy + loopback) into redsocks.
        rules = (
            "iptables -t nat -F OUTPUT; "
            "iptables -t nat -A OUTPUT -p tcp -d 127.0.0.1 -j RETURN; "
            f"iptables -t nat -A OUTPUT -p tcp -d {spec.host} -j RETURN; "
            "iptables -t nat -A OUTPUT -p tcp -j REDIRECT --to-ports 12345"
        )
        adb.shell(f"su -c '{rules}'", check=False)
        return f"{mode} via redsocks -> {spec.scheme}://{spec.host}:{spec.port}"

    raise ValueError(f"unknown proxy mode: {mode}")
