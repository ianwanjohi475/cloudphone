"""Multi-phone orchestration: create / list / stop / destroy Redroid phones.

Each phone is a privileged `redroid/redroid` container on the `cloudphone`
docker network, with its own persistent /data volume, adb port, fingerprint,
and optional proxy. The manager is the single source of truth the CLI and the
web dashboard both call.
"""

from __future__ import annotations

import json
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
            volumes={str(data_dir): {"bind": "/data", "mode": "rw"}},
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

    def create_many(
        self, count: int, profile: str = "pixel_7", proxy: Optional[str] = None
    ) -> list[Phone]:
        phones = []
        for _ in range(count):
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
        try:
            c.remove(force=True)
        except APIError:
            pass
        if wipe and idx >= 0:
            import shutil

            shutil.rmtree(self.s.data_root / f"redroid-{idx}", ignore_errors=True)
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
        idx = int(container.labels.get("io.cloudphone.index", "-1"))
        adb_port = self.s.adb_base_port + idx if idx >= 0 else 0
        return Phone(
            name=container.name,
            index=idx,
            container_id=container.short_id,
            status=container.status,
            adb_port=adb_port,
            adb_address=f"redroid-{idx}:5555",
            profile=container.labels.get("io.cloudphone.profile", "unknown"),
            proxy=container.labels.get("io.cloudphone.proxy", ""),
            labels=dict(container.labels),
        )
