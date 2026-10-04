import pytest

from cloudphone import camera


def test_media_kind():
    assert camera.media_kind("a.JPG") == "image"
    assert camera.media_kind("clip.mov") == "video"
    assert camera.media_kind("blob", "video/mp4") == "video"
    with pytest.raises(ValueError):
        camera.media_kind("app.apk")


def test_set_media_writes_source_line(tmp_path):
    src = tmp_path / "my selfie.png"
    src.write_bytes(b"png")
    phone = tmp_path / "emu-0"
    st = camera.set_media(phone, src, src.name)
    assert st.kind == "image"
    line = (phone / "camera" / "source").read_text().strip()
    kind, rel = line.split("|")
    assert kind == "image" and rel.startswith("uploads/")
    assert (phone / "camera" / rel).read_bytes() == b"png"
    assert " " not in rel  # safe for the feeder
    now = camera.state(phone)
    assert now.kind == "image" and now.source == "my_selfie.png"


def test_pattern_and_default_state(tmp_path):
    phone = tmp_path / "emu-1"
    assert camera.state(phone).kind == "pattern"
    camera.set_pattern(phone)
    assert (phone / "camera" / "source").read_text() == "pattern|\n"


def test_prune_keeps_current(tmp_path, monkeypatch):
    monkeypatch.setattr(camera, "KEEP_UPLOADS", 2)
    phone = tmp_path / "emu-0"
    for i in range(5):
        f = tmp_path / f"v{i}.mp4"
        f.write_bytes(b"v")
        camera.set_media(phone, f, f.name)
    files = list((phone / "camera" / "uploads").iterdir())
    assert len(files) == 2
    current = (phone / "camera" / "source").read_text().strip().split("|")[1]
    assert (phone / "camera" / current).exists()
