"""Pothole Cloud server (FastAPI).

Endpoints
  GET  /                  web app home (choose Scanner or Driver)
  WS   /ws/scan           scanner streams frames, gets boxes back, hits are saved to DB1
  POST /classify          one image -> boxes (no saving)
  POST /submit            one image + metadata -> saved to DB1
  POST /process           run the post-process notebook (papermill)
  GET  /process/status    state of the last run
  GET  /getpdata          potholes from DB.F as JSON (optionally near a point)
  GET  /route-potholes    route A -> B plus the potholes on it
  POST /feedback          driver says "still_there" or "gone"
"""
import json
import logging
import struct
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from . import db, geo, routing
from .config import settings
from .inference import get_detector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("pothole.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    settings.PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    settings.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    await run_in_threadpool(get_detector)   # load + warm up the model once
    log.info("Detector mode: %s", get_detector().mode)
    yield


app = FastAPI(title="Pothole Cloud", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=settings.WEB_DIR), name="static")
settings.PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.PHOTOS_DIR), name="media")


# ---------------------------------------------------------------- pages
@app.get("/")
def home():
    return FileResponse(settings.WEB_DIR / "index.html")


@app.get("/scanner")
def scanner_page():
    return FileResponse(settings.WEB_DIR / "scanner.html")


@app.get("/drive")
@app.get("/driver")
def driver_page():
    return FileResponse(settings.WEB_DIR / "driver.html")


@app.get("/api/config")
def app_config():
    return {
        "detector_mode": get_detector().mode,
        "camera_height_m": settings.DEFAULT_CAMERA_HEIGHT_M,
        "camera_tilt_deg": settings.DEFAULT_CAMERA_TILT_DEG,
        "hfov_deg": settings.DEFAULT_HFOV_DEG,
    }


# ---------------------------------------------------------------- helpers
def _num(v):
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _or(meta, key, default):
    v = _num(meta.get(key))
    return default if v is None else v


def save_photo(jpeg: bytes, device_id: str, seq) -> str:
    now = datetime.now(timezone.utc)
    rel = Path(now.strftime("%Y-%m-%d")) / f"{device_id or 'dev'}_{now.strftime('%H%M%S_%f')}_{seq}.jpg"
    path = settings.PHOTOS_DIR / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(jpeg)
    return str(rel)


def store_detections(jpeg: bytes, meta: dict, boxes: list, img_size) -> list:
    """Save the frame once and one DB1 row per box. Needs a GPS fix."""
    lat, lon = _num(meta.get("lat")), _num(meta.get("lon"))
    if not boxes or lat is None or lon is None:
        return []
    photo = save_photo(jpeg, str(meta.get("device_id", "")), meta.get("seq", 0))
    ids = []
    with db.session() as conn:
        for b in boxes:
            ids.append(db.insert_detection(conn, {
                "captured_at": meta.get("captured_at"),
                "device_id": meta.get("device_id"),
                "user_id": meta.get("user_id"),
                "lat": lat, "lon": lon,
                "gps_accuracy_m": _num(meta.get("gps_accuracy_m")),
                "heading_deg": _num(meta.get("heading_deg")),
                "speed_kmh": _num(meta.get("speed_kmh")),
                "camera_height_m": _or(meta, "camera_height_m", settings.DEFAULT_CAMERA_HEIGHT_M),
                "camera_tilt_deg": _or(meta, "camera_tilt_deg", settings.DEFAULT_CAMERA_TILT_DEG),
                "hfov_deg": _or(meta, "hfov_deg", settings.DEFAULT_HFOV_DEG),
                "img_w": img_size[0], "img_h": img_size[1],
                "photo_path": photo,
                "x1": b["x1"], "y1": b["y1"], "x2": b["x2"], "y2": b["y2"],
                "confidence": b["conf"],
                "damage_type": b.get("damage_type", "pothole"),
            }))
    return ids


def pothole_json(p: dict) -> dict:
    photo = p.get("crop_path") or p.get("best_photo_path")
    keep = ["damage_type", "id", "lat", "lon", "loc_accuracy_m", "severity", "ride_score", "width_m", "area_m2",
            "surface", "lane_position", "description", "times_seen", "first_seen", "last_seen",
            "status", "route_offset_m", "along_route_m"]
    out = {k: p.get(k) for k in keep if k in p}
    out["photo_url"] = f"/media/{photo}" if photo else None
    out["full_photo_url"] = f"/media/{p['best_photo_path']}" if p.get("best_photo_path") else None
    return out


# ---------------------------------------------------------------- scanning
def unpack_frame(msg: bytes):
    """Binary frame = 4-byte big-endian JSON length + JSON metadata + JPEG bytes."""
    (n,) = struct.unpack(">I", msg[:4])
    meta = json.loads(msg[4:4 + n].decode("utf-8"))
    return meta, msg[4 + n:]


def process_frame(meta: dict, jpeg: bytes) -> dict:
    det = get_detector()
    image = det.decode(jpeg)
    boxes, ms = det.predict(image)
    saved = store_detections(jpeg, meta, boxes, image.size)
    return {"seq": meta.get("seq"), "boxes": boxes, "saved": saved, "ms": ms,
            "img_w": image.size[0], "img_h": image.size[1]}


@app.websocket("/ws/scan")
async def ws_scan(ws: WebSocket):
    await ws.accept()
    log.info("Scanner connected")
    try:
        while True:
            msg = await ws.receive_bytes()
            try:
                meta, jpeg = unpack_frame(msg)
                result = await run_in_threadpool(process_frame, meta, jpeg)
            except Exception as e:  # bad frame: report and keep the connection
                log.warning("bad frame: %s", e)
                result = {"error": str(e)}
            await ws.send_json(result)
    except WebSocketDisconnect:
        log.info("Scanner disconnected")


@app.post("/classify")
async def classify(image: UploadFile = File(...)):
    jpeg = await image.read()
    det = get_detector()
    img = det.decode(jpeg)
    boxes, ms = await run_in_threadpool(det.predict, img)
    return {"boxes": boxes, "ms": ms, "img_w": img.size[0], "img_h": img.size[1]}


@app.post("/submit")
async def submit(image: UploadFile = File(...), meta: str = Form(...), boxes: str = Form(None)):
    """meta: JSON with lat, lon, heading_deg, ... ; boxes: optional JSON list (else we detect)."""
    jpeg = await image.read()
    meta_d = json.loads(meta)
    det = get_detector()
    img = det.decode(jpeg)
    box_list = json.loads(boxes) if boxes else (await run_in_threadpool(det.predict, img))[0]
    ids = await run_in_threadpool(store_detections, jpeg, meta_d, box_list, img.size)
    if not ids:
        raise HTTPException(400, "Nothing saved: need at least one box and a GPS fix (lat, lon).")
    return {"saved": ids}


# ---------------------------------------------------------------- post-process
_job = {"state": "idle", "started": None, "finished": None, "output": None, "error": None}
_job_lock = threading.Lock()


def _run_notebook():
    import papermill as pm
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = settings.RUNS_DIR / f"postprocess_{stamp}.ipynb"
    try:
        pm.execute_notebook(
            str(settings.NOTEBOOK_DIR / "02_postprocess.ipynb"), str(out),
            cwd=str(settings.NOTEBOOK_DIR), progress_bar=False,
        )
        _job.update(state="done", output=str(out))
    except Exception as e:
        log.exception("post-process failed")
        _job.update(state="failed", error=str(e), output=str(out))
    finally:
        _job["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")


@app.post("/process")
def start_process():
    with _job_lock:
        if _job["state"] == "running":
            return {"started": False, **_job}
        _job.update(state="running", error=None, output=None, finished=None,
                    started=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        threading.Thread(target=_run_notebook, daemon=True).start()
    return {"started": True, **_job}


@app.get("/process/status")
def process_status():
    with db.session() as conn:
        pending = conn.execute("SELECT COUNT(*) FROM detections WHERE processed=0").fetchone()[0]
        deferred_rows = conn.execute("SELECT process_note, COUNT(*) FROM detections WHERE processed=0 AND process_note IS NOT NULL GROUP BY process_note").fetchall()
        deferred = {row[0]: row[1] for row in deferred_rows}
        states = {row[0]: row[1] for row in conn.execute('SELECT status, COUNT(*) FROM potholes GROUP BY status')}
    return {**_job, "unprocessed_detections": pending, "new_detections": pending-sum(deferred.values()), "deferred_detections":sum(deferred.values()), "deferred_reasons":deferred, "map_records":states}


# ---------------------------------------------------------------- driver data
@app.get("/getpdata")
def getpdata(lat: float = None, lon: float = None, radius_m: float = Query(5000, le=50000),
             include_repaired: bool = False):
    statuses = ("open", "repaired") if include_repaired else ("open",)
    with db.session() as conn:
        if lat is not None and lon is not None:
            rows = db.potholes_in_box(conn, *geo.bbox_around(lat, lon, radius_m), statuses=statuses)
        else:
            rows = db.all_potholes(conn, statuses=statuses)
    return {"count": len(rows), "potholes": [pothole_json(p) for p in rows]}


def _parse_point(s: str):
    try:
        lat, lon = (float(x) for x in s.split(","))
        return lat, lon
    except ValueError:
        raise HTTPException(400, f"Bad point '{s}', expected 'lat,lon'")


@app.get("/route-potholes")
async def route_potholes(start: str, end: str):
    try:
        route = await routing.get_route(_parse_point(start), _parse_point(end))
    except Exception as e:
        raise HTTPException(502, f"Routing failed: {e}")
    with db.session() as conn:
        hits = routing.potholes_on_route(conn, route["coords"])
    severe = sum(1 for p in hits if p.get("severity") in ("High", "Critical"))
    return {**route, "count": len(hits), "severe_count": severe,
            "potholes": [pothole_json(p) for p in hits]}


class Feedback(BaseModel):
    pothole_id: int
    kind: str  # "still_there" | "gone"


@app.post("/feedback")
def feedback(fb: Feedback):
    if fb.kind not in ("still_there", "gone"):
        raise HTTPException(400, "kind must be 'still_there' or 'gone'")
    with db.session() as conn:
        try:
            return db.add_feedback(conn, fb.pothole_id, fb.kind)
        except KeyError:
            raise HTTPException(404, "Unknown pothole")

from .system_models import router as system_router
app.include_router(system_router)

@app.get('/api/drive/routes')
async def drive_routes(start: str, end: str):
    a, b = _parse_point(start), _parse_point(end)
    if not all(-90 <= x[0] <= 90 and -180 <= x[1] <= 180 for x in (a,b)):
        raise HTTPException(400, 'Invalid coordinates')
    try:
        choices = await routing.get_routes(a,b)
    except Exception as e:
        raise HTTPException(502, 'Routing service unavailable') from e
    with db.session() as conn:
        for route in choices:
            hits = routing.potholes_on_route(conn, route['coords'])
            route.update(potholes=[pothole_json(p) for p in hits], count=len(hits),
                         severe_count=sum(p.get('severity') in ('High','Critical') for p in hits))
    return {'routes': choices}

@app.get('/api/drive/search')
async def drive_search(q: str = Query(..., min_length=3, max_length=160)):
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get('https://photon.komoot.io/api/', params={'q':q,'limit':10,'lang':'en','bbox':'68,6,98,38'})
            r.raise_for_status()
        results=[]
        for feature in r.json().get('features',[]):
            props=feature['properties']; lon,lat=feature['geometry']['coordinates'][:2]
            if str(props.get('countrycode','')).lower() not in ('in','ind'):continue
            label=', '.join(dict.fromkeys(str(props[k]) for k in ('name','street','city','state','country') if props.get(k)))
            results.append({'label':label,'lat':lat,'lon':lon})
        return {'results':results}
    except Exception as e:
        raise HTTPException(502,'Location search unavailable; use map selection instead.') from e

@app.get('/api/drive/search-fallback')
async def search_fallback(q: str = Query(...,min_length=3,max_length=160)):
    import httpx
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response=await client.get('https://nominatim.openstreetmap.org/search',params={'q':q,'format':'json','limit':5,'countrycodes':'in','accept-language':'en'},headers={'User-Agent':'RoadPlotter-local-prototype/1.0'})
            response.raise_for_status()
        return {'results':[{'label':p['display_name'],'lat':float(p['lat']),'lon':float(p['lon'])} for p in response.json()]}
    except Exception as error:
        raise HTTPException(502,'Search providers are unavailable. Use map selection or enter latitude,longitude.') from error
