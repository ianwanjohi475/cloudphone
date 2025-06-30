import importlib

import cloudphone.config as cfg


def test_defaults(monkeypatch):
    for k in ("REDROID_WIDTH", "REDROID_GPU_MODE", "ADB_BASE_PORT"):
        monkeypatch.delenv(k, raising=False)
    importlib.reload(cfg)
    s = cfg.Settings()
    assert s.width == 720
    assert s.gpu_mode == "guest"
    assert s.adb_base_port == 5555
    assert s.name_prefix == "cloudphone-redroid-"


def test_env_override(monkeypatch):
    monkeypatch.setenv("REDROID_GPU_MODE", "host")
    monkeypatch.setenv("ADB_BASE_PORT", "6000")
    s = cfg.Settings()
    assert s.gpu_mode == "host"
    assert s.adb_base_port == 6000


def test_as_dict_serializable():
    s = cfg.Settings()
    d = s.as_dict()
    assert isinstance(d["data_root"], str)
