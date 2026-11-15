# cloudphone

An Android phone with the real Google Play Store, running on your Ubuntu
machine and used from a browser tab. One command starts it and prints a link.

```bash
git clone https://github.com/ianwanjohi475/cloudphone.git
```

```bash
cd cloudphone
```

```bash
./cloudphone start
```

The first run downloads Android (about 2 GB) and asks for your sudo password to
install a few packages. It then prints a link like
`http://localhost:8080/?key=…`. Open it: the phone appears as soon as Android
has booted (a few minutes the first time).

To use the phone from another device or network, get a public https link:

```bash
./cloudphone share
```

Anyone who has that link controls the phone, including the Google account
signed in on it, so share it only with people you trust. The link changes
every time the tunnel restarts.

## What you need

- Ubuntu on an Intel/AMD (x86_64) machine, 8 GB RAM or more, 20 GB free disk.
- Hardware virtualization (`/dev/kvm`). `./cloudphone doctor` checks it.
  - PC or laptop: enable Intel VT-x / AMD-V in the BIOS.
  - WSL2: Windows 11, with `nestedVirtualization=true` under `[wsl2]` in
    `%UserProfile%\.wslconfig`, then `wsl --shutdown`.
  - VPS: only ones that offer KVM / nested virtualization.

Without `/dev/kvm` the phone cannot run; there is no slow fallback.

## Installing apps

- **Play Store:** press *Play Store* in the side bar, sign in with a Google
  account, install as on any phone.
- **App files:** drag an `.apk`, `.xapk`, `.apks` or `.apkm` onto the page, or
  press *Install file*. From the terminal: `./cloudphone install game.xapk`.

The phone is Google's own Android 14 image, certified for Google Play, and it
translates ARM code, so most apps and games install and run. What will not
work: apps that refuse emulators or demand hardware-backed Play Integrity
(many banking apps, some games with anti-cheat), and anything needing a real
SIM, camera or Bluetooth.

## Using it

- Click or touch = tap. Drag = swipe. Mouse wheel scrolls. Right click = Back.
- Type on your keyboard; paste with Ctrl+V. On a phone or tablet, press
  *Keyboard* to bring up your device's keyboard.
- Apps, accounts and files survive `stop` / `start`.

## Commands

| Command | What it does |
| --- | --- |
| `./cloudphone start` | Install what is missing, boot the phone, print the link |
| `./cloudphone share` | Same, plus a public https link (Cloudflare quick tunnel) |
| `./cloudphone link` | Print the link(s) again |
| `./cloudphone install <file>` | Install an app file |
| `./cloudphone status` / `logs` | What is running / recent log lines |
| `./cloudphone stop` | Power off (data is kept) |
| `./cloudphone reset` | Factory reset: deletes the phone's apps and data |
| `./cloudphone doctor` | Check this machine can run it |

Settings are environment variables, for example
`PORT=8090 RAM_MB=6144 CORES=6 ./cloudphone start`. See the top of
[`cloudphone`](cloudphone) for the full list. Screen size, RAM and cores apply
from the next `start`; changing `API` (Android version) needs a `reset`.

Everything lives in `~/.cloudphone`.

## How it works

```
browser tab ──WebSocket──> server/app.py ──adb──> Android Emulator (KVM)
   canvas  <── H.264 ─────  relays frames <─────── scrcpy server on the phone
   touch   ─── JSON ──────> control msgs  ───────> injected as real touches
```

- `cloudphone`: bash launcher. Installs the Android SDK emulator and a Google
  Play system image, creates the virtual phone, runs it headless.
- `server/app.py`: one Python file (aiohttp). Starts
  [scrcpy](https://github.com/Genymobile/scrcpy)'s server on the phone and
  relays its H.264 video to the page, which decodes it with WebCodecs. Touches
  and keys go back over scrcpy's control channel. If that cannot start, or the
  browser cannot decode H.264 (for example when the page is opened over plain
  http from another machine), it falls back to screenshots: slower, but it
  works everywhere.
- The server listens on `127.0.0.1` only and every request needs the access
  key from the link. `share` exposes it through a Cloudflare quick tunnel.

## Development

```bash
python3 -m unittest discover tests
```

`tests/fake_adb.py` stands in for a phone (an ffmpeg test pattern as the
screen), so the server and page can be run without Android. The fake never
reads the streamer file, so any existing file will do for `CP_SCRCPY_JAR`:

```bash
CP_ADB=tests/fake_adb.py CP_SCRCPY_JAR=LICENSE python3 server/app.py
```

MIT licensed.
