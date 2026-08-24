"""
camera_manager.py
------------------
Manages the lifecycle of camera worker tasks dynamically (add/edit/refresh/
delete from the dashboard, no app restart needed).

RELIABILITY FIXES in this version (root cause of "not all cameras loaded",
"video keeps reconnecting/sliding", and "violations failing to load"):

1. THROTTLED DB STATUS WRITES: previously `db.update_camera_status()` was
   called on EVERY loop iteration (~100x/second per camera). With 16
   cameras that is up to ~1600 writes/second hammering PostgreSQL, which
   exhausts the connection pool. Now it's throttled to once every
   config.CAMERA_STATUS_UPDATE_INTERVAL seconds per camera (default 4s).

2. SELF-HEALING LOOP: previously any unexpected exception inside a
   camera's loop (e.g. a transient DB timeout, a cv2 decode hiccup, a
   momentary network blip) would propagate up and permanently kill that
   camera's asyncio task - the camera would simply stop, look "stuck" on
   the dashboard, and never recover without a manual restart of the whole
   app. Now each loop iteration's body is wrapped in try/except: on any
   non-cancellation error, it's logged and the loop continues on the next
   iteration instead of dying. This is what was silently killing camera
   workers under load (explaining cameras that "don't all load"), and
   contributing to DB pool exhaustion cascading into /api/violations
   failures for the whole app.

3. RETRY-SAFE VIOLATION LOGGING: a violation is only marked as "already
   alerted" AFTER its DB write succeeds. If db.log_violation() fails
   (e.g. transient pool exhaustion), the same violation is retried on the
   next frame instead of being silently dropped - so a temporary DB hiccup
   no longer means a lost/unsaved violation image+record.
"""
import os
import cv2
import time
import asyncio
import logging
from typing import Dict, Optional, Callable

from . import config, db
from .stream_handler import RTSPStream
from .compliance_engine import ComplianceEngine
from .ws_hub import hub

logger = logging.getLogger("ppe.camera_manager")

BOX_COLOR_VIOLATION = (0, 0, 255)
BOX_COLOR_OK = (0, 200, 0)


def _draw_annotations(frame, statuses, camera_label: str):
    for status in statuses:
        x1, y1, x2, y2 = status.box
        color = BOX_COLOR_VIOLATION if status.is_violation else BOX_COLOR_OK
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"ID{status.track_id} " + (
            "VIOLATION: " + ",".join(sorted(status.missing_ppe)) if status.is_violation else "OK"
        )
        cv2.putText(frame, label, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    cv2.putText(frame, camera_label, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(frame, time.strftime("%Y-%m-%d %H:%M:%S"), (10, frame.shape[0] - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    return frame


class CameraManager:
    def __init__(self, detector_getter: Callable[[], object], alert_manager):
        self._detector_getter = detector_getter
        self._alert_manager = alert_manager
        self._tasks: Dict[str, asyncio.Task] = {}
        self._streams: Dict[str, RTSPStream] = {}

    async def start_camera(self, camera: dict):
        camera_id = camera["camera_id"]
        if camera_id in self._tasks:
            logger.info(f"[{camera_id}] already running, skipping start")
            return
        stream = RTSPStream(camera_id, camera["rtsp_url"]).start()
        self._streams[camera_id] = stream
        task = asyncio.create_task(self._camera_worker(camera, stream))
        self._tasks[camera_id] = task
        logger.info(f"[{camera_id}] worker started (area_group={camera.get('area_group_name')})")

    async def stop_camera(self, camera_id: str):
        task = self._tasks.pop(camera_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"[{camera_id}] worker task raised on stop: {e}")
        stream = self._streams.pop(camera_id, None)
        if stream:
            stream.stop()
        try:
            await db.delete_camera_status(camera_id)
        except Exception as e:
            logger.warning(f"[{camera_id}] could not clear camera_status row: {e}")
        logger.info(f"[{camera_id}] worker stopped")

    async def refresh_camera(self, camera_id: str) -> bool:
        """Stop + restart using the LATEST DB row. This is the handler
        behind both the dashboard's per-camera 'Reconnect' button (Feeds
        tab) and the Cameras tab's 'Refresh' button - same operation,
        two entry points."""
        camera = await db.get_camera(camera_id)
        if not camera:
            return False
        await self.stop_camera(camera_id)
        if camera["enabled"]:
            await self.start_camera(camera)
        return True

    async def reconcile_all(self):
        cameras = await db.list_cameras()
        started = 0
        for cam in cameras:
            if cam["enabled"]:
                try:
                    await self.start_camera(cam)
                    started += 1
                except Exception as e:
                    # A failure starting ONE camera must never prevent the
                    # rest from starting - this loop continues regardless.
                    logger.error(f"[{cam['camera_id']}] failed to start during reconcile: {e}")
        logger.info(f"Reconciled {len(cameras)} camera(s) from DB ({started} started)")

    async def stop_all(self):
        for camera_id in list(self._tasks.keys()):
            await self.stop_camera(camera_id)

    def is_running(self, camera_id: str) -> bool:
        return camera_id in self._tasks

    def get_stream(self, camera_id: str) -> Optional[RTSPStream]:
        return self._streams.get(camera_id)

    def running_camera_ids(self):
        return list(self._tasks.keys())

    async def _camera_worker(self, camera: dict, stream: RTSPStream):
        camera_id = camera["camera_id"]
        camera_name = camera["name"]
        area_group_id = camera.get("area_group_id")
        area_group_name = camera.get("area_group_name") or "Unassigned"
        required_ppe = camera["required_ppe"]

        engine = ComplianceEngine(camera_id, required_ppe)
        frame_count = 0
        last_statuses = []
        already_alerted_ids = set()
        broadcast_interval = 1.0 / max(1, config.BROADCAST_FPS)
        last_broadcast = 0.0
        last_status_write = 0.0

        logger.info(f"[{camera_id}] worker loop entering (self-healing enabled)")

        while True:
            try:
                frame = stream.read()
                if frame is None:
                    await asyncio.sleep(0.2)
                    continue

                frame_count += 1
                if frame_count % config.FRAME_SKIP == 0:
                    detector = self._detector_getter()
                    detections = await asyncio.to_thread(detector.infer, frame)
                    last_statuses = engine.evaluate(detections)

                    for status in last_statuses:
                        if not status.is_violation:
                            already_alerted_ids.discard((status.track_id, tuple(sorted(status.missing_ppe))))
                            continue

                        for violation_type in status.missing_ppe:
                            alert_key = (status.track_id, violation_type)
                            if alert_key in already_alerted_ids:
                                continue

                            try:
                                os.makedirs(config.SNAPSHOT_DIR, exist_ok=True)
                                snapshot_filename = f"{camera_id}_{violation_type}_{int(time.time())}.jpg"
                                snapshot_path = os.path.join(config.SNAPSHOT_DIR, snapshot_filename)
                                evidence_frame = _draw_annotations(
                                    frame.copy(), last_statuses, f"{camera_name} ({area_group_name})")
                                cv2.imwrite(snapshot_path, evidence_frame)

                                violation_id = await db.log_violation(
                                    camera_id, camera_name, area_group_name, status.track_id,
                                    violation_type, snapshot_path, area_group_id, area_group_name,
                                )
                                matches = await self._alert_manager.handle_violation(
                                    violation_id, camera_id, camera_name, area_group_name,
                                    status.track_id, violation_type, snapshot_path,
                                )
                                # Only mark as alerted AFTER a successful DB write, so a
                                # transient DB error causes a RETRY next frame instead of
                                # silently losing this violation.
                                already_alerted_ids.add(alert_key)

                                await hub.broadcast_event({
                                    "type": "violation",
                                    "violation_id": violation_id,
                                    "camera_id": camera_id,
                                    "camera_name": camera_name,
                                    "zone": area_group_name,
                                    "area_group": area_group_name,
                                    "violation_type": violation_type,
                                    "track_id": status.track_id,
                                    "snapshot_url": f"/api/snapshot/{violation_id}",
                                    "rules_matched": [m.rule_name for m in matches],
                                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                                })
                                logger.info(f"[{camera_id}] VIOLATION id={violation_id} type={violation_type} "
                                            f"area_group={area_group_name}")
                            except Exception as e:
                                # Do NOT add to already_alerted_ids - retry next frame.
                                logger.warning(f"[{camera_id}] failed to log/alert violation "
                                                f"'{violation_type}' (will retry next frame): {e}")

                now = time.time()
                if now - last_broadcast >= broadcast_interval:
                    annotated = _draw_annotations(frame.copy(), last_statuses, f"{camera_name} ({area_group_name})")
                    ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, config.JPEG_QUALITY])
                    if ok:
                        await hub.broadcast_frame(camera_id, buf.tobytes())
                    last_broadcast = now

                # THROTTLED status write - was previously every loop tick
                # (~100x/sec/camera); now at most once per
                # CAMERA_STATUS_UPDATE_INTERVAL seconds. This single change
                # is the main fix for DB pool exhaustion under many cameras.
                if now - last_status_write >= config.CAMERA_STATUS_UPDATE_INTERVAL:
                    try:
                        await db.update_camera_status(camera_id, camera_name, area_group_name,
                                                       stream.connected, stream.last_frame_time)
                    except Exception as e:
                        logger.warning(f"[{camera_id}] status update failed (non-fatal): {e}")
                    last_status_write = now

                await asyncio.sleep(0.01)

            except asyncio.CancelledError:
                logger.info(f"[{camera_id}] worker cancelled (stop/refresh requested)")
                raise
            except Exception as e:
                # SELF-HEALING: any other unexpected error (DB blip, cv2
                # decode error, transient network issue) is logged and the
                # loop CONTINUES instead of the whole camera task dying.
                logger.error(f"[{camera_id}] unexpected error in worker loop (continuing): "
                             f"{type(e).__name__}: {e}")
                await asyncio.sleep(1.0)
