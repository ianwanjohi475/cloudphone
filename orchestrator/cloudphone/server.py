"""Web dashboard + JSON API.

Serves a control panel that lists phones, shows health, exposes lifecycle
actions, and links each phone into the ws-scrcpy web client for live control.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import gps as gps_mod
from . import health as health_mod
from .adb import Adb

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
    phones = mgr.create_many(
        int(body.get("count", 1)),
        profile=body.get("profile", "pixel_7"),
        proxy=body.get("proxy"),
    )
    return {"created": [p.to_dict() for p in phones]}


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
