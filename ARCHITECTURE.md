# Sentinel — Architecture

## Design Goals
- No dashboard lag: binary WebSocket frame push, per-client size-1 queues.
- Accurate detection: YOLOv8/v11 + N-consecutive-frame violation confirmation.
- Durable, concurrent-safe storage: PostgreSQL (asyncpg pool).
- DB-driven alerting: alert conditions live as rows in `alert_rules`.
- Dynamic camera management: cameras/area groups are DB-backed, editable at
  runtime, with zero-downtime restarts of individual camera streams.

## Cameras & Area Groups

```sql
area_groups (id, name, description)
cameras (id, camera_id, name, rtsp_url, area_group_id -> area_groups.id,
         required_ppe[], enabled)
```

On first boot (empty `cameras` table), `app/db.py`'s `_seed_if_empty()`
loads `config.SEED_CAMERAS` (your 16 real plant cameras) and
`config.SEED_AREA_GROUPS` (9 logical groupings) into these tables. After
that, `config.py` is never read again for camera config - all
add/edit/refresh/delete goes through `/api/cameras` and `/api/area-groups`.

`app/camera_manager.py` owns the runtime lifecycle:
- `start_camera(row)` / `stop_camera(id)` / `refresh_camera(id)` (stop+start
  using the LATEST DB row - this is what makes RTSP URL edits take effect)
- `reconcile_all()` - called once at startup, starts every enabled camera.

## Data Flow
```
RTSP Camera -> RTSPStream (thread, always-latest-frame, auto-reconnect)
            -> PPEDetector (YOLO, off event loop via asyncio.to_thread)
            -> ComplianceEngine (person<->PPE matching + violation streak)
            -> on confirmed violation:
                 - save annotated snapshot to disk
                 - db.log_violation() -> PostgreSQL, incl. area_group_id/name
                 - rules_engine.evaluate() -> matches alert_rules
                 - alert_manager dispatches Teams/email, logs alert_dispatch_log
                 - ws_hub.broadcast_event() -> dashboard live feed updates
            -> ws_hub.broadcast_frame() -> dashboard live video tile updates
```

## Why WebSockets instead of MJPEG
Per-client size-1 queues: a new frame always replaces the previous
unconsumed one - no backlog regardless of client network speed.

## Why PostgreSQL + Rules Engine
PostgreSQL handles concurrent writes from multiple camera workers natively.
Rules engine decouples alert conditions from code - editable live via
`/api/rules` or the dashboard, no redeploy.
