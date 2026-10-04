from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from cloudphone import server


class FakeMgr:
    def __init__(self, root, engine="emulator"):
        self.root = root
        self.engine = engine

    def get(self, name):
        if name != "cloudphone-emu-0":
            raise ValueError(f"no such phone: {name}")
        return SimpleNamespace(
            engine=self.engine, data_dir="emu-0", adb_address="x:5555", adb_port=6555
        )

    def data_path(self, phone):
        return self.root / phone.data_dir


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_mgr", lambda: FakeMgr(tmp_path))
    return TestClient(server.app), tmp_path


def test_camera_upload_and_reset(client):
    c, root = client
    r = c.post(
        "/api/phones/cloudphone-emu-0/camera",
        files={"file": ("face.jpg", b"jpg", "image/jpeg")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "image"
    assert (root / "emu-0/camera/source").read_text().startswith("image|uploads/")
    assert c.get("/api/phones/cloudphone-emu-0/camera").json()["source"] == "face.jpg"
    r = c.post("/api/phones/cloudphone-emu-0/camera")
    assert r.json()["kind"] == "pattern"


def test_camera_rejects_non_media(client):
    c, _ = client
    r = c.post(
        "/api/phones/cloudphone-emu-0/camera",
        files={"file": ("app.apk", b"x", "application/octet-stream")},
    )
    assert r.status_code == 415


def test_camera_needs_real_phone(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_mgr", lambda: FakeMgr(tmp_path, engine="redroid"))
    r = TestClient(server.app).get("/api/phones/cloudphone-emu-0/camera")
    assert r.status_code == 409


def test_install_reports_hint(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(server.Adb, "connect", lambda self: True)

    def boom(adb, path, replace_incompatible=False):
        assert path.name == "game.xapk" and path.read_bytes() == b"zip"
        raise server.packages.InstallError("INSTALL_FAILED_OLDER_SDK", "Failure")

    monkeypatch.setattr(server.packages, "install_any", boom)
    r = c.post(
        "/api/phones/cloudphone-emu-0/install",
        files={"file": ("game.xapk", b"zip")},
        data={"replace": "false"},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "INSTALL_FAILED_OLDER_SDK"


def test_lifecycle_route_does_not_shadow_gps(client):
    c, _ = client
    paths = [r.path for r in server.app.routes]
    assert paths.index("/api/phones/{name}/gps") < paths.index("/api/phones/{name}/{action}")
