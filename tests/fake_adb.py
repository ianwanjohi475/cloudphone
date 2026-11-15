#!/usr/bin/env python3
"""A stand-in for `adb` so the server and web page can be tested without a
phone. It answers the handful of adb commands the server uses, and plays the
part of scrcpy's server with an H.264 test pattern from ffmpeg.

Everything it is asked to do is appended to $FAKE_ADB_DIR/calls.log.
"""

import json
import os
import socket
import struct
import subprocess
import sys
from pathlib import Path

STATE = Path(os.environ.get("FAKE_ADB_DIR", "/tmp/fake-adb"))
STATE.mkdir(parents=True, exist_ok=True)


def record(entry) -> None:
    with (STATE / "calls.log").open("a") as f:
        f.write(json.dumps(entry) + "\n")


def nal_units(stream):
    """Split an Annex B byte stream into NAL units (without start codes)."""
    buf = b""
    while chunk := stream.read(4096):
        buf += chunk
        while True:
            start = buf.find(b"\x00\x00\x01")
            nxt = buf.find(b"\x00\x00\x01", start + 3) if start >= 0 else -1
            if nxt < 0:
                break
            yield buf[start + 3 : nxt].rstrip(b"\x00")
            buf = buf[nxt:]


def scrcpy_server(args: list[str]) -> None:
    scid = next(a.split("=", 1)[1] for a in args if a.startswith("scid="))
    port = int((STATE / f"forward-scrcpy_{scid}").read_text())
    srv = socket.create_server(("127.0.0.1", port))
    video, _ = srv.accept()
    video.sendall(b"\x00")
    control, _ = srv.accept()
    print("[server] INFO: Device: fake", flush=True)

    if os.fork() == 0:  # log every control message we receive
        while data := control.recv(65536):
            record({"control": data.hex()})
        os._exit(0)

    ff = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-re", "-f", "lavfi", "-i", "testsrc=size=360x800:rate=15",
         "-c:v", "libx264", "-profile:v", "baseline", "-pix_fmt", "yuv420p", "-tune", "zerolatency",
         "-x264-params", "keyint=30:slices=1:sliced-threads=0:aud=0:repeat-headers=1", "-f", "h264", "-"],
        stdout=subprocess.PIPE,
    )  # fmt: skip
    config, pts = b"", 0
    for nal in nal_units(ff.stdout):
        kind = nal[0] & 0x1F
        data = b"\x00\x00\x00\x01" + nal
        if kind in (7, 8):
            config += data
            continue
        if kind not in (1, 5):
            continue
        try:
            if config:
                video.sendall(struct.pack(">QI", 1 << 63, len(config)) + config)
                config = b""
            flags = (1 << 62) if kind == 5 else 0
            video.sendall(struct.pack(">QI", flags | pts, len(data)) + data)
        except OSError:
            break
        pts += 66666
    ff.kill()


def main() -> None:
    args = sys.argv[1:]
    if args[:1] == ["-s"]:
        args = args[2:]
    cmd, rest = (args[0], args[1:]) if args else ("", [])
    out = sys.stdout

    if cmd == "shell" and any("com.genymobile.scrcpy.Server" in a for a in rest):
        if os.environ.get("FAKE_ADB_NO_SCRCPY"):
            print("ERROR: scrcpy disabled for this test")
            sys.exit(1)
        record({"scrcpy": rest})
        return scrcpy_server(rest)

    record({"cmd": cmd, "args": rest})
    if cmd == "get-state":
        out.write("device\n")
    elif cmd == "shell":
        line = " ".join(rest)
        if "sys.boot_completed" in line:
            out.write("1\n")
        elif "abilist" in line:
            out.write("x86_64,arm64-v8a\n")
        elif "stat -c" in line:
            for f in sorted((STATE / "sdcard").glob("*")):
                out.write(f"regular file|{f.stat().st_size}|{int(f.stat().st_mtime)}|{f.name}\n")
        elif line.startswith("rm -f -- "):
            import shlex

            (STATE / "sdcard" / Path(shlex.split(line)[3]).name).unlink(missing_ok=True)
    elif cmd == "push" and rest[1].startswith("/sdcard/"):
        (STATE / "sdcard").mkdir(exist_ok=True)
        (STATE / "sdcard" / Path(rest[1]).name).write_bytes(Path(rest[0]).read_bytes())
        out.write("1 file pushed\n")
    elif cmd == "forward" and rest[0] != "--remove":
        (STATE / f"forward-{rest[1].split(':', 1)[1]}").write_text(rest[0].split(":", 1)[1])
    elif cmd == "exec-out":
        png = STATE / "screen.png"
        if not png.exists():
            subprocess.run(
                ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=360x800",
                 "-frames:v", "1", str(png)], check=True)  # fmt: skip
        out.buffer.write(png.read_bytes())
    elif cmd in ("install", "install-multiple"):
        out.write("Performing Streamed Install\nSuccess\n")


if __name__ == "__main__":
    main()
