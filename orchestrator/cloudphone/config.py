"""Central configuration, read from environment with sane defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path


def _env(key: str, default: str) -> str:
    val = os.environ.get(key)
    return val if val not in (None, "") else default


@dataclass
class Settings:
    # Image / android
    redroid_image: str = field(
        default_factory=lambda: _env("REDROID_IMAGE", "redroid/redroid:13.0.0-latest")
    )
    android_version: str = field(default_factory=lambda: _env("ANDROID_VERSION", "13.0.0"))

    # Display
    width: int = field(default_factory=lambda: int(_env("REDROID_WIDTH", "720")))
    height: int = field(default_factory=lambda: int(_env("REDROID_HEIGHT", "1280")))
    dpi: int = field(default_factory=lambda: int(_env("REDROID_DPI", "320")))
    fps: int = field(default_factory=lambda: int(_env("REDROID_FPS", "30")))

    # GPU
    gpu_mode: str = field(default_factory=lambda: _env("REDROID_GPU_MODE", "guest"))
    gpu_node: str = field(default_factory=lambda: _env("REDROID_GPU_NODE", "/dev/dri/renderD128"))

    # Resources
    memory: str = field(default_factory=lambda: _env("REDROID_MEMORY", "4g"))
    cpus: float = field(default_factory=lambda: float(_env("REDROID_CPUS", "2")))

    # Networking
    adb_base_port: int = field(default_factory=lambda: int(_env("ADB_BASE_PORT", "5555")))
    network: str = "cloudphone"

    # Storage
    data_root: Path = field(default_factory=lambda: Path(_env("DATA_ROOT", "./data")).resolve())

    # Proxy default
    default_proxy: str = field(default_factory=lambda: _env("DEFAULT_PROXY", ""))

    # Labels used to find our containers
    label_key: str = "io.cloudphone.managed"
    name_prefix: str = "cloudphone-redroid-"

    def as_dict(self) -> dict:
        d = asdict(self)
        d["data_root"] = str(self.data_root)
        return d


SETTINGS = Settings()
