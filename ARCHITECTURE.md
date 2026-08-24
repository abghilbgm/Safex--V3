# Sentinel — Architecture

## Design Goals
- **No dashboard lag**: binary WebSocket frame push with per-client size-1 queues.
- **Accurate detection**: YOLOv8/v11 + N-consecutive-frame violation confirmation.
- **Durable, concurrent-safe storage**: PostgreSQL (asyncpg pool).
- **DB-driven alerting**: alert conditions live as rows in `alert_rules`.
- **Dynamic camera management**: cameras and area groups are DB-backed entities,
  addable/editable/removable from the dashboard at runtime, with zero-downtime
  restarts of individual camera streams.

## Cameras & Area Groups (new)

Two new tables replace the old hardcoded `config.CAMERAS` list:

```sql
area_groups (id, name, description)
cameras (id, camera_id, name, rtsp_url, area_group_id -> area_groups.id,
         required_ppe[], enabled)
```

`app/camera_manager.py` owns the runtime lifecycle:
- `start_camera(row)` — spins up an `RTSPStream` + an asyncio worker task for one camera.
- `stop_camera(camera_id)` — cancels the task, stops the stream, clears camera_status.
- `refresh_camera(camera_id)` — stop + start using the LATEST DB row. This is
  what makes editing a camera's RTSP URL take effect: the API handler calls
  `db.update_camera()` then `camera_manager.refresh_camera()`, which re-reads
  the row (now with the new URL) and reconnects — no other camera is touched.
- `reconcile_all()` — called once at startup: starts a worker for every
  `enabled` camera currently in the DB.

Each camera's worker loop (moved into `camera_manager.py`) does the same
inference -> compliance -> violation -> alert -> broadcast pipeline as
before, now parameterized by the DB row instead of a static config entry,
and tagging every violation with `area_group_id` / `area_group` (denormalized
at write-time, so historical violations keep the group they were logged
under even if the camera's group assignment changes later).

## Data Flow
```
RTSP Camera -> RTSPStream (thread, always-latest-frame, auto-reconnect)
            -> PPEDetector (YOLO, off the event loop via asyncio.to_thread)
            -> ComplianceEngine (person<->PPE matching + violation streak)
            -> on confirmed violation:
                 - save annotated snapshot to disk (unchanged mechanism)
                 - db.log_violation() -> PostgreSQL, incl. area_group_id/name
                 - rules_engine.evaluate() -> matches `alert_rules`
                 - alert_manager dispatches Teams/email, logs to `alert_dispatch_log`
                 - ws_hub.broadcast_event() -> dashboard's live feed updates instantly
            -> ws_hub.broadcast_frame() -> dashboard's live video tile updates instantly
```

## Why WebSockets instead of MJPEG
Per-client size-1 queues mean a new frame always replaces the previous
unconsumed one - no backlog regardless of client network speed.

## Why PostgreSQL + Rules Engine
PostgreSQL handles concurrent writes from multiple camera workers natively
(unlike SQLite). The rules engine decouples alert conditions from code:
rules match on camera_id/zone/violation_type (any wildcardable), each with
independent cooldown throttling, editable live via `/api/rules` or the
dashboard - no redeploy needed. The same pattern now extends to camera
management itself: `/api/cameras` and `/api/area-groups` let you reconfigure
the whole camera fleet without touching a config file or restarting the app.

## Deployment Topology (Docker Compose)
One `postgres` service + one `ppe-app` service. All camera CRUD/refresh
operations work identically regardless of container count; for very large
camera fleets, run additional app containers and use `PPE_CAMERA_IDS` to
partition which cameras each instance's `reconcile_all()` picks up.
