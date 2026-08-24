"""
camera_manager.py
------------------
Manages the lifecycle of camera worker tasks dynamically, so cameras can be
added, edited (including RTSP URL), refreshed, or removed from the
dashboard at runtime - WITHOUT restarting the whole application.

Each camera gets:
  - one RTSPStream (threaded frame grabber)
  - one asyncio worker task (inference -> compliance -> violation logging
    -> alert dispatch -> WebSocket broadcast)

"Refresh" (used after editing a camera's RTSP URL, or via the dashboard's
explicit Refresh button) simply stops the existing stream+task for that
camera and starts a fresh one with the current DB row - this cleanly
recovers from stale connections without touching any other camera.
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
        """
        detector_getter: zero-arg callable returning the current PPEDetector
                         instance (a callable, not the instance itself, so
                         the detector can be lazily created after startup).
        alert_manager:    shared AlertManager instance.
        """
        self._detector_getter = detector_getter
        self._alert_manager = alert_manager
        self._tasks: Dict[str, asyncio.Task] = {}
        self._streams: Dict[str, RTSPStream] = {}

    # -- Public lifecycle API (called from REST endpoints in main.py) ------
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
        await db.delete_camera_status(camera_id)
        logger.info(f"[{camera_id}] worker stopped")

    async def refresh_camera(self, camera_id: str) -> bool:
        """Stops and restarts the camera's stream+worker using the LATEST DB
        row (picks up any RTSP URL / required_ppe / area group changes)."""
        camera = await db.get_camera(camera_id)
        if not camera:
            return False
        await self.stop_camera(camera_id)
        if camera["enabled"]:
            await self.start_camera(camera)
        return True

    async def reconcile_all(self):
        """Called once at app startup: starts a worker for every enabled
        camera currently in the DB."""
        cameras = await db.list_cameras()
        for cam in cameras:
            if cam["enabled"]:
                await self.start_camera(cam)
        logger.info(f"Reconciled {len(cameras)} camera(s) from DB "
                    f"({sum(1 for c in cameras if c['enabled'])} started)")

    async def stop_all(self):
        for camera_id in list(self._tasks.keys()):
            await self.stop_camera(camera_id)

    def is_running(self, camera_id: str) -> bool:
        return camera_id in self._tasks

    def get_stream(self, camera_id: str) -> Optional[RTSPStream]:
        return self._streams.get(camera_id)

    def running_camera_ids(self):
        return list(self._tasks.keys())

    # -- The actual per-camera inference/alert/broadcast loop --------------
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

        try:
            while True:
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

                now = time.time()
                if now - last_broadcast >= broadcast_interval:
                    annotated = _draw_annotations(frame.copy(), last_statuses, f"{camera_name} ({area_group_name})")
                    ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, config.JPEG_QUALITY])
                    if ok:
                        await hub.broadcast_frame(camera_id, buf.tobytes())
                    last_broadcast = now

                await db.update_camera_status(camera_id, camera_name, area_group_name,
                                               stream.connected, stream.last_frame_time)
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            logger.info(f"[{camera_id}] worker cancelled (stop/refresh requested)")
            raise
