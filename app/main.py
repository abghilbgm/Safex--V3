"""
main.py — FastAPI app: dynamic camera lifecycle, area groups, WebSocket
video/events, REST API, alert rules CRUD, snapshot image serving.

KEY ENDPOINT for the "cameras missing from frontend" fix:
  POST /api/cameras/sync-seed
    Runs db.sync_seed_data() on demand - tops up any of the 16 seed
    cameras that are missing from the DB (e.g. because a previous
    startup only partially completed), WITHOUT touching any camera that
    already exists. Safe to call any number of times. Exposed as a
    "Sync Default Cameras" button in the dashboard's Cameras tab.
"""
import os
import sys
import time
import json
import asyncio
import traceback
from contextlib import asynccontextmanager
from typing import Dict, Optional, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from . import config, db
from .detector import PPEDetector
from .alert_manager import AlertManager
from .camera_manager import CameraManager
from .ws_hub import hub


def _out(msg: str):
    print(msg, file=sys.stderr, flush=True)


_detector: Optional[PPEDetector] = None
_alert_manager = AlertManager()
_camera_manager: Optional[CameraManager] = None


def _get_detector():
    return _detector


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        _out("=" * 70)
        _out("SENTINEL PPE COMPLIANCE SYSTEM - STARTING UP")
        _out("=" * 70)
        _out("[1/3] Connecting to database...")
        await db.init_pool()

        os.makedirs(config.SNAPSHOT_DIR, exist_ok=True)

        global _detector, _camera_manager
        _out(f"[2/3] Loading detection model from {os.path.abspath(config.MODEL_PATH)} ...")
        if not os.path.isfile(config.MODEL_PATH):
            raise FileNotFoundError(
                f"\n\n================ MODEL FILE NOT FOUND ================\n"
                f"Expected a YOLO model at: {os.path.abspath(config.MODEL_PATH)}\n"
                f"Fix - run BEFORE starting the app:\n"
                f"  docker compose run --rm ppe-app python scripts/download_model.py\n"
                f"Then restart: docker compose restart ppe-app\n"
                f"========================================================\n"
            )
        _detector = PPEDetector()
        _out("      Model loaded successfully.")

        _out("[3/3] Starting camera workers...")
        _camera_manager = CameraManager(_get_detector, _alert_manager)
        await _camera_manager.reconcile_all()

        _out("=" * 70)
        _out("STARTUP COMPLETE - application is ready.")
        _out("=" * 70)

    except BaseException:
        _out("!" * 70)
        _out("STARTUP FAILED - FULL TRACEBACK BELOW")
        _out("!" * 70)
        _out(traceback.format_exc())
        _out("!" * 70)
        raise

    yield

    if _camera_manager:
        await _camera_manager.stop_all()
    await db.close_pool()


app = FastAPI(title="PPE Compliance Detection System", lifespan=lifespan)

DASHBOARD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard")
if os.path.isdir(DASHBOARD_DIR):
    app.mount("/static", StaticFiles(directory=DASHBOARD_DIR), name="static")


@app.websocket("/ws/video/{camera_id}")
async def ws_video(websocket: WebSocket, camera_id: str):
    await websocket.accept()
    q = await hub.subscribe_video(camera_id)
    try:
        while True:
            frame_bytes = await q.get()
            await websocket.send_bytes(frame_bytes)
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unsubscribe_video(camera_id, q)


@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    await websocket.accept()
    q = await hub.subscribe_events()
    try:
        while True:
            event = await q.get()
            await websocket.send_text(json.dumps(event))
    except WebSocketDisconnect:
        pass
    finally:
        await hub.unsubscribe_events(q)


@app.get("/")
async def root():
    index_path = os.path.join(DASHBOARD_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return {"service": "PPE Compliance Detection System"}


@app.get("/api/health")
async def health():
    return {"status": "ok", "time": time.strftime("%Y-%m-%d %H:%M:%S"), "ws": hub.stats()}


class CameraIn(BaseModel):
    camera_id: str
    name: str
    rtsp_url: str
    area_group_id: Optional[int] = None
    required_ppe: List[str] = ["helmet", "vest"]
    enabled: bool = True


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    rtsp_url: Optional[str] = None
    area_group_id: Optional[int] = None
    required_ppe: Optional[List[str]] = None
    enabled: Optional[bool] = None


@app.get("/api/cameras")
async def list_cameras():
    try:
        cameras = await db.list_cameras()
        statuses = {s["camera_id"]: s for s in await db.get_camera_statuses()}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error while listing cameras: {e}")

    out = []
    for cam in cameras:
        persisted = statuses.get(cam["camera_id"], {})
        live_running = _camera_manager.is_running(cam["camera_id"]) if _camera_manager else False
        out.append({
            "camera_id": cam["camera_id"],
            "name": cam["name"],
            "area_group_id": cam["area_group_id"],
            "area_group_name": cam["area_group_name"],
            "required_ppe": cam["required_ppe"],
            "enabled": cam["enabled"],
            "connected": persisted.get("connected", False) if live_running else False,
            "worker_running": live_running,
        })
    return out


@app.get("/api/cameras/{camera_id}")
async def get_camera(camera_id: str):
    cam = await db.get_camera(camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    return cam


@app.post("/api/cameras")
async def add_camera(camera: CameraIn):
    existing = await db.get_camera(camera.camera_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"Camera '{camera.camera_id}' already exists")

    await db.create_camera(
        camera.camera_id, camera.name, camera.rtsp_url, camera.area_group_id,
        camera.required_ppe, camera.enabled,
    )
    full = await db.get_camera(camera.camera_id)
    if camera.enabled:
        await _camera_manager.start_camera(full)
    return full


@app.post("/api/cameras/sync-seed")
async def sync_seed_cameras():
    """Manually tops up any of the 16 seed cameras (from app/config.py)
    that are missing from the database - WITHOUT touching cameras that
    already exist. This is the fix for cameras that never made it into
    the DB during a previous partial/crashed startup. After syncing, any
    newly-added camera is also started immediately if enabled."""
    result = await db.sync_seed_data()
    for camera_id in result["newly_created_camera_ids"]:
        full = await db.get_camera(camera_id)
        if full and full["enabled"]:
            await _camera_manager.start_camera(full)
    return result


@app.put("/api/cameras/{camera_id}")
async def edit_camera(camera_id: str, update: CameraUpdate):
    existing = await db.get_camera(camera_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Camera not found")

    fields = {k: v for k, v in update.model_dump().items() if v is not None}
    if not fields:
        return existing

    rtsp_changed = "rtsp_url" in fields and fields["rtsp_url"] != existing["rtsp_url"]
    enabled_changed = "enabled" in fields and fields["enabled"] != existing["enabled"]

    await db.update_camera(camera_id, **fields)
    updated = await db.get_camera(camera_id)

    if rtsp_changed or enabled_changed or "required_ppe" in fields:
        if updated["enabled"]:
            await _camera_manager.refresh_camera(camera_id)
        else:
            await _camera_manager.stop_camera(camera_id)

    return updated


@app.post("/api/cameras/{camera_id}/refresh")
async def refresh_camera(camera_id: str):
    ok = await _camera_manager.refresh_camera(camera_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Camera not found")
    return {"camera_id": camera_id, "refreshed": True}


@app.delete("/api/cameras/{camera_id}")
async def remove_camera(camera_id: str):
    existing = await db.get_camera(camera_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Camera not found")
    await _camera_manager.stop_camera(camera_id)
    await db.delete_camera(camera_id)
    return {"deleted": camera_id}


class AreaGroupIn(BaseModel):
    name: str
    description: str = ""


class AreaGroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


@app.get("/api/area-groups")
async def list_area_groups():
    try:
        return await db.list_area_groups()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error while listing area groups: {e}")


@app.post("/api/area-groups")
async def add_area_group(group: AreaGroupIn):
    return await db.create_area_group(group.name, group.description)


@app.put("/api/area-groups/{group_id}")
async def edit_area_group(group_id: int, update: AreaGroupUpdate):
    fields = {k: v for k, v in update.model_dump().items() if v is not None}
    updated = await db.update_area_group(group_id, **fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Area group not found")
    return updated


@app.delete("/api/area-groups/{group_id}")
async def remove_area_group(group_id: int):
    ok = await db.delete_area_group(group_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Area group not found")
    return {"deleted": group_id}


@app.get("/api/violations")
async def violations(limit: int = 50, camera_id: Optional[str] = None,
                      violation_type: Optional[str] = None, area_group_id: Optional[int] = None):
    try:
        rows = await db.get_recent_violations(limit, camera_id, violation_type, area_group_id)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error while loading violations: {e}")

    for row in rows:
        row["snapshot_url"] = f"/api/snapshot/{row['id']}" if row.get("snapshot_path") else None
    return JSONResponse(rows)


@app.get("/api/stats")
async def stats(window_hours: int = 24):
    try:
        return JSONResponse(await db.get_compliance_stats(window_hours))
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error while loading stats: {e}")


@app.get("/api/export/violations.csv")
async def export_violations_csv(limit: int = 5000):
    import csv, io
    rows = await db.get_recent_violations(limit)
    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=violations.csv"},
    )


@app.get("/api/snapshot/{violation_id}")
async def get_snapshot(violation_id: int):
    violation = await db.get_violation_by_id(violation_id)
    if not violation or not violation.get("snapshot_path"):
        raise HTTPException(status_code=404, detail="No snapshot found for this violation")
    path = violation["snapshot_path"]
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Snapshot file missing on disk: {path}")
    return FileResponse(path, media_type="image/jpeg")


class RuleIn(BaseModel):
    name: str
    camera_id: Optional[str] = None
    zone: Optional[str] = None
    violation_type: Optional[str] = None
    min_severity: int = 1
    channels: List[str] = ["teams"]
    cooldown_seconds: int = 300
    email_recipients: List[str] = []
    enabled: bool = True


class RuleUpdate(BaseModel):
    name: Optional[str] = None
    camera_id: Optional[str] = None
    zone: Optional[str] = None
    violation_type: Optional[str] = None
    min_severity: Optional[int] = None
    channels: Optional[List[str]] = None
    cooldown_seconds: Optional[int] = None
    email_recipients: Optional[List[str]] = None
    enabled: Optional[bool] = None


@app.get("/api/rules")
async def get_rules():
    try:
        return JSONResponse(await db.list_rules())
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database error while loading rules: {e}")


@app.post("/api/rules")
async def add_rule(rule: RuleIn):
    created = await db.create_rule(
        rule.name, rule.camera_id, rule.zone, rule.violation_type, rule.min_severity,
        rule.channels, rule.cooldown_seconds, rule.email_recipients, rule.enabled,
    )
    await _alert_manager.rules_engine.force_refresh()
    return JSONResponse(created)


@app.put("/api/rules/{rule_id}")
async def edit_rule(rule_id: int, rule: RuleUpdate):
    fields = {k: v for k, v in rule.model_dump().items() if v is not None}
    updated = await db.update_rule(rule_id, **fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Rule not found")
    await _alert_manager.rules_engine.force_refresh()
    return JSONResponse(updated)


@app.delete("/api/rules/{rule_id}")
async def remove_rule(rule_id: int):
    ok = await db.delete_rule(rule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found")
    await _alert_manager.rules_engine.force_refresh()
    return {"deleted": rule_id}


def run():
    try:
        uvicorn.run(app, host=config.API_HOST, port=config.API_PORT)
    except BaseException:
        _out("!" * 70)
        _out("UVICORN FAILED TO START. Full traceback:")
        _out("!" * 70)
        _out(traceback.format_exc())
        _out("!" * 70)
        raise


if __name__ == "__main__":
    run()
