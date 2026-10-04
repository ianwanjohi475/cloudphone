"""Web dashboard + JSON API.

Serves a control panel that lists phones, shows health, exposes lifecycle
actions, and links each phone into the ws-scrcpy web client for live control.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import camera as camera_mod
from . import gps as gps_mod
from . import health as health_mod
from . import packages
from .adb import Adb, AdbError

WEB = Path(__file__).parent / "web"
templates = Jinja2Templates(directory=str(WEB / "templates"))

app = FastAPI(title="cloudphone", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(WEB / "static")), name="static")

SCRCPY_PORT = int(os.environ.get("SCRCPY_PORT", "8000"))


def _mgr():
    from .manager import PhoneManager

    return PhoneManager()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "scrcpy_port": SCRCPY_PORT},
    )


@app.get("/api/phones")
def api_phones():
    mgr = _mgr()
    out = []
    for p in mgr.list():
        try:
            c = mgr.client.containers.get(p.name)
        except Exception:
            c = None
        h = health_mod.check(p, c) if p.status == "running" else None
        d = p.to_dict()
        d["health"] = h.to_dict() if h else None
        out.append(d)
    return {"phones": out}


@app.post("/api/phones")
async def api_create(request: Request):
    body = await request.json()
    mgr = _mgr()
    try:
        phones = mgr.create_many(
            int(body.get("count", 1)),
            profile=body.get("profile", "pixel_7"),
            proxy=body.get("proxy"),
            engine=body.get("engine", "redroid"),
        )
    except (RuntimeError, ValueError) as e:
        raise HTTPException(400, str(e))
    return {"created": [p.to_dict() for p in phones]}


# ---------------------------------------------------------------- apps
def _adb_for(name: str) -> Adb:
    from .manager import adb_address

    try:
        phone = _mgr().get(name)
    except ValueError as e:
        raise HTTPException(404, str(e))
    adb = Adb(adb_address(phone), timeout=60)
    adb.connect()
    return adb


def _save_upload(upload: UploadFile, folder: str) -> Path:
    name = Path(upload.filename or "upload").name
    dest = Path(folder) / name
    with dest.open("wb") as out:
        shutil.copyfileobj(upload.file, out, length=1 << 20)
    return dest


@app.post("/api/phones/{name}/install")
def api_install(name: str, file: UploadFile = File(...), replace: bool = Form(False)):
    """Install an uploaded .apk / .xapk / .apks / .apkm / .zip."""
    adb = _adb_for(name)
    with tempfile.TemporaryDirectory(prefix="cloudphone-upload-") as tmp:
        path = _save_upload(file, tmp)
        try:
            res = packages.install_any(adb, path, replace_incompatible=replace)
        except packages.InstallError as e:
            raise HTTPException(422, {"code": e.code, "hint": e.hint, "detail": e.detail[-2000:]})
        except (ValueError, AdbError) as e:
            raise HTTPException(422, {"code": "BAD_FILE", "hint": str(e), "detail": ""})
    return {"ok": True, **res.to_dict()}


@app.get("/api/phones/{name}/apps")
def api_apps(name: str):
    adb = _adb_for(name)
    return {"apps": packages.app_list(adb), "abis": packages.device_abis(adb)}


@app.post("/api/phones/{name}/apps/{package}/{verb}")
def api_app_action(name: str, package: str, verb: str):
    adb = _adb_for(name)
    try:
        if verb == "launch":
            out = packages.launch(adb, package)
        elif verb == "uninstall":
            out = packages.uninstall(adb, package)
        else:
            raise HTTPException(400, f"unknown app action {verb}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "output": out}


# ---------------------------------------------------------------- camera
def _phone_data(name: str):
    mgr = _mgr()
    try:
        phone = mgr.get(name)
    except ValueError as e:
        raise HTTPException(404, str(e))
    if phone.engine != "emulator":
        raise HTTPException(
            409,
            "Camera upload needs a 'Real phone' (Android Emulator engine). "
            "Redroid phones have no camera driver.",
        )
    return mgr.data_path(phone)


@app.get("/api/phones/{name}/camera")
def api_camera_state(name: str):
    return camera_mod.state(_phone_data(name)).to_dict()


@app.post("/api/phones/{name}/camera")
def api_camera_set(name: str, file: UploadFile | None = File(None)):
    """Upload a photo or video: every app that opens the camera sees it.
    Post with no file to go back to the test pattern."""
    data = _phone_data(name)
    if file is None or not file.filename:
        return camera_mod.set_pattern(data).to_dict()
    with tempfile.TemporaryDirectory(prefix="cloudphone-cam-") as tmp:
        path = _save_upload(file, tmp)
        try:
            st = camera_mod.set_media(data, path, file.filename, file.content_type or "")
        except ValueError as e:
            raise HTTPException(415, str(e))
    return st.to_dict()


@app.post("/api/phones/{name}/gps")
async def api_gps(name: str, request: Request):
    body = await request.json()
    phone = _mgr().get(name)
    adb = Adb(phone.adb_address)
    adb.connect()
    gps_mod.enable_mock(adb)
    status = gps_mod.set_location(
        adb, gps_mod.Location(lat=float(body["lat"]), lon=float(body["lon"]))
    )
    return {"ok": True, "status": status}


@app.get("/api/health")
def api_health():
    mgr = _mgr()
    out = []
    for p in mgr.list():
        try:
            c = mgr.client.containers.get(p.name)
        except Exception:
            c = None
        out.append(health_mod.check(p, c).to_dict())
    return JSONResponse({"health": out})


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


# Catch-all lifecycle route goes last so /gps, /install and /camera win.
@app.post("/api/phones/{name}/{action}")
def api_action(name: str, action: str):
    mgr = _mgr()
    try:
        if action == "start":
            mgr.start(name)
        elif action == "stop":
            mgr.stop(name)
        elif action == "restart":
            mgr.restart(name)
        elif action == "destroy":
            mgr.destroy(name)
        else:
            raise HTTPException(400, f"unknown action {action}")
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True, "name": name, "action": action}
