"""Multi-phone orchestration: create / list / stop / destroy Redroid phones.

Each phone is a privileged `redroid/redroid` container on the `cloudphone`
docker network, with its own persistent /data volume, adb port, fingerprint,
and optional proxy. The manager is the single source of truth the CLI and the
web dashboard both call.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

try:
    import docker
    from docker.errors import NotFound, APIError
except ImportError:  # pragma: no cover - docker SDK is a runtime dep
    docker = None

from .config import SETTINGS, Settings
from .fingerprint import Fingerprint, generate, stability_props


@dataclass
class Phone:
    name: str
    index: int
    container_id: str
    status: str
    adb_port: int
    adb_address: str  # reachable from inside the cloudphone network
    profile: str
    proxy: str = ""
    engine: str = "redroid"  # redroid | emulator
    data_dir: str = ""  # folder under DATA_ROOT holding this phone's /data
    labels: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.__dict__


class PhoneManager:
    def __init__(self, settings: Settings = SETTINGS):
        self.s = settings
        if docker is None:
            raise RuntimeError("docker SDK not installed; pip install docker")
        self.client = docker.from_env()
        self._ensure_network()

    # infra ------------------------------------------------------------------
    def _ensure_network(self) -> None:
        try:
            self.client.networks.get(self.s.network)
        except NotFound:
            self.client.networks.create(self.s.network, driver="bridge")

    def _redroid_command(self) -> list[str]:
        return [
            f"androidboot.redroid_width={self.s.width}",
            f"androidboot.redroid_height={self.s.height}",
            f"androidboot.redroid_dpi={self.s.dpi}",
            f"androidboot.redroid_fps={self.s.fps}",
            f"androidboot.redroid_gpu_mode={self.s.gpu_mode}",
            "androidboot.use_memfd=1",
            "androidboot.redroid_net_ndns=1",
        ]

    # lifecycle --------------------------------------------------------------
    def create(
        self,
        index: Optional[int] = None,
        profile: str = "pixel_7",
        proxy: Optional[str] = None,
        memory: Optional[str] = None,
        cpus: Optional[float] = None,
    ) -> Phone:
        if index is None:
            index = self._next_index()
        name = f"{self.s.name_prefix}{index}"
        if self._find(name):
            raise ValueError(f"phone {name} already exists")

        data_dir = self.s.data_root / f"redroid-{index}"
        data_dir.mkdir(parents=True, exist_ok=True)

        # Persist the device identity so recreation keeps the same fingerprint.
        fp = generate(profile=profile, seed=name)
        (data_dir.parent / f"{name}.fingerprint.json").write_text(fp.to_json())

        adb_port = self.s.adb_base_port + index
        devices = []
        if self.s.gpu_mode == "host":
            devices.append(f"{self.s.gpu_node}:{self.s.gpu_node}:rwm")

        container = self.client.containers.run(
            self.s.redroid_image,
            command=self._redroid_command(),
            name=name,
            hostname=f"redroid-{index}",
            detach=True,
            privileged=True,
            network=self.s.network,
            restart_policy={"Name": "unless-stopped"},
            ports={"5555/tcp": adb_port},
            volumes={
                str(self.s.host_data_root / f"redroid-{index}"): {"bind": "/data", "mode": "rw"}
            },
            devices=devices,
            mem_limit=memory or self.s.memory,
            nano_cpus=int((cpus or self.s.cpus) * 1e9),
            labels={
                self.s.label_key: "true",
                "io.cloudphone.index": str(index),
                "io.cloudphone.profile": profile,
                "io.cloudphone.proxy": proxy or self.s.default_proxy or "",
            },
        )
        return self._to_phone(container)

    def create_emulator(
        self,
        index: Optional[int] = None,
        profile: str = "pixel_6",
        proxy: Optional[str] = None,
    ) -> Phone:
        """A full Android Emulator phone: Google Play, ARM app translation, and a
        camera fed from uploaded photos/videos. Needs /dev/kvm on the host."""
        if not _host_dev_exists("kvm"):
            raise RuntimeError(
                "/dev/kvm is missing: this host cannot run real-phone (emulator) phones. "
                "Enable virtualization (VT-x/AMD-V) or use a KVM-capable VPS."
            )
        if index is None:
            index = self._next_index()
        name = f"{self.s.emulator_prefix}{index}"
        if self._find(name):
            raise ValueError(f"phone {name} already exists")
        datadir = f"emu-{index}"
        data_dir = self.s.data_root / datadir
        (data_dir / "camera" / "uploads").mkdir(parents=True, exist_ok=True)
        _share_adb_key(data_dir)

        devices = ["/dev/kvm:/dev/kvm:rwm"]
        video = f"/dev/video{self.s.camera_video_base + index}"
        if _host_dev_exists(video.rsplit("/", 1)[1]):
            devices.append(f"{video}:/dev/video0:rwm")

        adb_port = self.s.emulator_adb_base_port + index
        container = self.client.containers.run(
            self.s.emulator_image,
            name=name,
            hostname=datadir,
            detach=True,
            network=self.s.network,
            restart_policy={"Name": "unless-stopped"},
            ports={"5555/tcp": adb_port},
            volumes={str(self.s.host_data_root / datadir): {"bind": "/data", "mode": "rw"}},
            devices=devices,
            environment={
                "DEVICE": profile,
                "RAM_MB": str(self.s.emulator_ram_mb),
                "CORES": str(self.s.emulator_cores),
                "PROXY": proxy or self.s.default_proxy or "",
            },
            labels={
                self.s.label_key: "true",
                "io.cloudphone.index": str(index),
                "io.cloudphone.profile": profile,
                "io.cloudphone.proxy": proxy or self.s.default_proxy or "",
                "io.cloudphone.engine": "emulator",
                "io.cloudphone.adb": f"{name}:5555",
                "io.cloudphone.adbport": str(adb_port),
                "io.cloudphone.datadir": datadir,
            },
        )
        return self._to_phone(container)

    def create_many(
        self,
        count: int,
        profile: str = "pixel_7",
        proxy: Optional[str] = None,
        engine: str = "redroid",
    ) -> list[Phone]:
        phones = []
        for _ in range(count):
            if engine == "emulator":
                phones.append(self.create_emulator(proxy=proxy))
            else:
                phones.append(self.create(profile=profile, proxy=proxy))
        return phones

    def stop(self, name: str) -> None:
        c = self._require(name)
        c.stop(timeout=20)

    def start(self, name: str) -> None:
        self._require(name).start()

    def restart(self, name: str) -> None:
        self._require(name).restart(timeout=20)

    def destroy(self, name: str, wipe: bool = False) -> None:
        c = self._require(name)
        idx = int(c.labels.get("io.cloudphone.index", "-1"))
        datadir = c.labels.get("io.cloudphone.datadir") or f"redroid-{idx}"
        try:
            c.remove(force=True)
        except APIError:
            pass
        if wipe and idx >= 0:
            import shutil

            shutil.rmtree(self.s.data_root / datadir, ignore_errors=True)
            (self.s.data_root / f"{self.s.name_prefix}{idx}.fingerprint.json").unlink(
                missing_ok=True
            )

    # queries ----------------------------------------------------------------
    def list(self) -> list[Phone]:
        containers = self.client.containers.list(
            all=True, filters={"label": f"{self.s.label_key}=true"}
        )
        phones = [self._to_phone(c) for c in containers]
        return sorted(phones, key=lambda p: p.index)

    def get(self, name: str) -> Phone:
        return self._to_phone(self._require(name))

    def data_path(self, phone: Phone):
        return self.s.data_root / phone.data_dir

    def load_fingerprint(self, name: str) -> Optional[Fingerprint]:
        path = self.s.data_root / f"{name}.fingerprint.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return Fingerprint(**data)

    def stability_props(self) -> dict:
        return stability_props(self.s.gpu_mode)

    # helpers ----------------------------------------------------------------
    def _next_index(self) -> int:
        used = {p.index for p in self.list()}
        i = 0
        while i in used:
            i += 1
        return i

    def _find(self, name: str):
        try:
            return self.client.containers.get(name)
        except NotFound:
            return None

    def _require(self, name: str):
        c = self._find(name)
        if not c:
            raise ValueError(f"no such phone: {name}")
        return c

    def _to_phone(self, container) -> Phone:
        labels = container.labels
        idx = int(labels.get("io.cloudphone.index", "-1"))
        if "io.cloudphone.adbport" in labels:
            adb_port = int(labels["io.cloudphone.adbport"])
        else:
            adb_port = self.s.adb_base_port + idx if idx >= 0 else 0
        return Phone(
            name=container.name,
            index=idx,
            container_id=container.short_id,
            status=container.status,
            adb_port=adb_port,
            # Docker DNS resolves container names (not hostnames) on the network.
            adb_address=labels.get("io.cloudphone.adb") or f"{container.name}:5555",
            profile=labels.get("io.cloudphone.profile", "unknown"),
            proxy=labels.get("io.cloudphone.proxy", ""),
            engine=labels.get("io.cloudphone.engine", "redroid"),
            data_dir=labels.get("io.cloudphone.datadir") or f"redroid-{idx}",
            labels=dict(labels),
        )


def _share_adb_key(data_dir) -> None:
    """Give a new real phone this process's adb key pair so our adb is trusted.

    Play Store images reject adb clients whose key the emulator was not given
    ("device unauthorized"); the emulator reads it from <data>/.android/."""
    import shutil
    import subprocess
    from pathlib import Path

    home = Path(os.environ.get("ANDROID_USER_HOME") or Path.home() / ".android")
    key = home / "adbkey"
    if not key.exists() and shutil.which("adb"):
        home.mkdir(parents=True, exist_ok=True)
        subprocess.run(["adb", "keygen", str(key)], capture_output=True, check=False)
    if not key.exists():
        return
    dest = Path(data_dir) / ".android"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(key, dest / "adbkey")
    pub = key.with_suffix(".pub")
    if pub.exists():
        shutil.copyfile(pub, dest / "adbkey.pub")


def _host_dev_exists(node: str) -> bool:
    """Is /dev/<node> present on the docker host? The dashboard container sees
    the host's /dev at $HOST_DEV (mounted read-only in docker-compose.yml)."""
    return os.path.exists(os.path.join(os.environ.get("HOST_DEV", "/dev"), node))


def adb_address(phone: Phone) -> str:
    """Where to reach the phone's adb from *this* process.

    Inside the dashboard container the phone's hostname resolves on the
    cloudphone network; on the host only the published port does."""
    if os.path.exists("/.dockerenv"):
        return phone.adb_address
    return f"127.0.0.1:{phone.adb_port}"
