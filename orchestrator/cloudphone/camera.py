"""Uploaded photo/video -> phone camera.

Each emulator phone runs camera-feed.sh, which keeps its virtual webcam fed
from <phone data dir>/camera/source. Setting the camera is therefore just:
copy the upload into <data>/camera/uploads/ and rewrite that one line. Any app
on the phone that opens the camera (front or back) sees the uploaded media,
looping, until something else is uploaded.
"""

from __future__ import annotations

import mimetypes
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".3gp", ".mpeg", ".mpg", ".ts"}
KEEP_UPLOADS = 10


@dataclass
class CameraState:
    kind: str  # image | video | pattern
    source: str  # original file name, "" for the pattern
    since: float

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def media_kind(filename: str, content_type: str = "") -> str:
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXT or content_type.startswith("image/"):
        return "image"
    if ext in VIDEO_EXT or content_type.startswith("video/"):
        return "video"
    guess = mimetypes.guess_type(filename)[0] or ""
    if guess.startswith("image/"):
        return "image"
    if guess.startswith("video/"):
        return "video"
    raise ValueError(f"{filename} is not a photo or video")


def safe_name(filename: str) -> str:
    stem = re.sub(r"[^\w.-]+", "_", Path(filename).name).strip("._") or "upload"
    return f"{time.time_ns()}_{stem}"[:120]


def camera_dir(phone_data: Path) -> Path:
    d = Path(phone_data) / "camera"
    (d / "uploads").mkdir(parents=True, exist_ok=True)
    return d


def set_media(phone_data: Path, src: Path, filename: str, content_type: str = "") -> CameraState:
    """Copy an uploaded file into the phone's camera folder and switch the feed to it."""
    kind = media_kind(filename, content_type)
    d = camera_dir(phone_data)
    name = safe_name(filename)
    shutil.copyfile(src, d / "uploads" / name)
    _write_source(d, kind, f"uploads/{name}")
    _prune(d)
    return CameraState(kind=kind, source=Path(filename).name, since=time.time())


def set_pattern(phone_data: Path) -> CameraState:
    _write_source(camera_dir(phone_data), "pattern", "")
    return CameraState(kind="pattern", source="", since=time.time())


def state(phone_data: Path) -> CameraState:
    f = Path(phone_data) / "camera" / "source"
    if not f.exists():
        return CameraState(kind="pattern", source="", since=0)
    kind, _, rel = f.read_text().strip().partition("|")
    original = rel.rsplit("/", 1)[-1].split("_", 1)[-1] if rel else ""
    return CameraState(kind=kind or "pattern", source=original, since=f.stat().st_mtime)


def _write_source(d: Path, kind: str, rel: str) -> None:
    tmp = d / "source.tmp"
    tmp.write_text(f"{kind}|{rel}\n")
    tmp.replace(d / "source")  # atomic: the feeder never reads half a line


def _prune(d: Path) -> None:
    current = (d / "source").read_text().strip().partition("|")[2]
    files = sorted((d / "uploads").iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[KEEP_UPLOADS:]:
        if f"uploads/{old.name}" != current:
            old.unlink(missing_ok=True)
