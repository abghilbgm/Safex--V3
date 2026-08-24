"""
db.py — async PostgreSQL data layer (asyncpg, connection-pooled).

`sync_seed_data()` is the fix for cameras silently missing from the
frontend: it runs on EVERY app startup AND is exposed via
POST /api/cameras/sync-seed (a dashboard button), and works per-camera:
  - ensures every area group in SEED_AREA_GROUPS exists (create if missing)
  - for each camera in SEED_CAMERAS, if its camera_id does NOT already
    exist in the DB, create it. Existing cameras (including ones you've
    manually edited) are left completely untouched.
This makes seeding idempotent and self-healing: no matter how many times
it runs, or how the DB got into a partial state (e.g. only 1 of 16
cameras made it in during a previous crashed/interrupted run), every seed
camera that is still missing gets added, and nothing that already exists
gets touched or duplicated.
"""
import asyncio
import logging
import sys
import time
from typing import Optional, List, Dict, Any

import asyncpg

from . import config

logger = logging.getLogger("ppe.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS area_groups (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cameras (
    id BIGSERIAL PRIMARY KEY,
    camera_id TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    rtsp_url TEXT NOT NULL,
    area_group_id BIGINT REFERENCES area_groups(id) ON DELETE SET NULL,
    required_ppe TEXT[] NOT NULL DEFAULT '{helmet,vest}',
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS violations (
    id BIGSERIAL PRIMARY KEY,
    camera_id TEXT NOT NULL,
    camera_name TEXT,
    zone TEXT,
    area_group_id BIGINT,
    area_group TEXT,
    track_id INTEGER,
    violation_type TEXT NOT NULL,
    confidence_note TEXT,
    snapshot_path TEXT,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    epoch_time DOUBLE PRECISION NOT NULL,
    alert_dispatched BOOLEAN DEFAULT false
);
CREATE INDEX IF NOT EXISTS idx_violations_time ON violations (epoch_time DESC);
CREATE INDEX IF NOT EXISTS idx_violations_camera ON violations (camera_id);
CREATE INDEX IF NOT EXISTS idx_violations_type ON violations (violation_type);
CREATE INDEX IF NOT EXISTS idx_violations_area_group ON violations (area_group_id);

CREATE TABLE IF NOT EXISTS camera_status (
    camera_id TEXT PRIMARY KEY,
    camera_name TEXT,
    zone TEXT,
    connected BOOLEAN,
    last_frame_epoch DOUBLE PRECISION,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alert_rules (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    camera_id TEXT,
    zone TEXT,
    violation_type TEXT,
    min_severity INTEGER NOT NULL DEFAULT 1,
    channels TEXT[] NOT NULL DEFAULT '{teams}',
    cooldown_seconds INTEGER NOT NULL DEFAULT 300,
    email_recipients TEXT[] DEFAULT '{}',
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alert_dispatch_log (
    id BIGSERIAL PRIMARY KEY,
    violation_id BIGINT REFERENCES violations(id) ON DELETE CASCADE,
    rule_id BIGINT REFERENCES alert_rules(id) ON DELETE SET NULL,
    channel TEXT NOT NULL,
    success BOOLEAN NOT NULL,
    dispatched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

_pool: Optional[asyncpg.Pool] = None


def _print_flush(msg: str):
    print(msg, file=sys.stderr, flush=True)


async def init_pool():
    global _pool
    deadline = time.time() + config.PG_CONNECT_RETRY_SECONDS
    attempt = 0
    last_error = None

    while time.time() < deadline:
        attempt += 1
        try:
            _pool = await asyncpg.create_pool(
                host=config.PG_HOST, port=config.PG_PORT, database=config.PG_DB,
                user=config.PG_USER, password=config.PG_PASSWORD,
                min_size=config.PG_POOL_MIN, max_size=config.PG_POOL_MAX,
                timeout=10,
            )
            async with _pool.acquire() as conn:
                await conn.execute(SCHEMA)
            _print_flush(f"[ppe.db] PostgreSQL pool ready ({config.PG_HOST}:{config.PG_PORT}/{config.PG_DB}) "
                         f"pool_size={config.PG_POOL_MIN}-{config.PG_POOL_MAX} after {attempt} attempt(s)")
            result = await sync_seed_data()
            _print_flush(f"[ppe.db] Seed sync: {result['groups_created']} area group(s) created, "
                         f"{result['cameras_created']} camera(s) created, "
                         f"{result['cameras_already_existed']} already existed")
            return _pool
        except Exception as e:
            last_error = e
            _print_flush(
                f"[ppe.db] [attempt {attempt}] Could not connect to PostgreSQL at "
                f"{config.PG_HOST}:{config.PG_PORT}/{config.PG_DB} - {type(e).__name__}: {e}. "
                f"Retrying in 3s... (giving up after {config.PG_CONNECT_RETRY_SECONDS}s total)"
            )
            await asyncio.sleep(3)

    error_msg = (
        f"\n\n================ DATABASE CONNECTION FAILED ================\n"
        f"Could not connect to PostgreSQL after {attempt} attempts over "
        f"{config.PG_CONNECT_RETRY_SECONDS} seconds.\n"
        f"  Host: {config.PG_HOST}  Port: {config.PG_PORT}  DB: {config.PG_DB}  User: {config.PG_USER}\n"
        f"Last error: {type(last_error).__name__}: {last_error}\n"
        f"==============================================================\n"
    )
    _print_flush(error_msg)
    raise RuntimeError(error_msg) from last_error


async def close_pool():
    if _pool:
        await _pool.close()


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized - call init_pool() at startup")
    return _pool


async def sync_seed_data() -> Dict[str, Any]:
    """Idempotent top-up: creates any area group / camera from
    config.SEED_AREA_GROUPS / config.SEED_CAMERAS that doesn't already
    exist (matched by name / camera_id respectively). Never touches or
    duplicates anything that already exists. Safe to call any number of
    times - at startup, and on-demand via POST /api/cameras/sync-seed."""
    groups_created = 0
    cameras_created = 0

    existing_groups = await list_area_groups()
    group_name_to_id = {g["name"]: g["id"] for g in existing_groups}

    for group in config.SEED_AREA_GROUPS:
        if group["name"] not in group_name_to_id:
            row = await create_area_group(group["name"], group.get("description", ""))
            group_name_to_id[group["name"]] = row["id"]
            groups_created += 1

    existing_cameras = await list_cameras()
    existing_camera_ids = {c["camera_id"] for c in existing_cameras}
    newly_created_camera_ids: List[str] = []

    for cam in config.SEED_CAMERAS:
        if cam["camera_id"] in existing_camera_ids:
            continue
        area_group_id = group_name_to_id.get(cam.get("area_group_name"))
        await create_camera(
            cam["camera_id"], cam["name"], cam["rtsp_url"], area_group_id,
            cam.get("required_ppe", ["helmet", "vest"]),
        )
        cameras_created += 1
        newly_created_camera_ids.append(cam["camera_id"])

    return {
        "groups_created": groups_created,
        "cameras_created": cameras_created,
        "cameras_already_existed": len(existing_camera_ids),
        "newly_created_camera_ids": newly_created_camera_ids,
    }


async def list_area_groups() -> List[Dict[str, Any]]:
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """SELECT ag.*, COUNT(c.id) as camera_count
               FROM area_groups ag
               LEFT JOIN cameras c ON c.area_group_id = ag.id
               GROUP BY ag.id ORDER BY ag.name ASC"""
        )
        return [dict(r) for r in rows]


async def create_area_group(name: str, description: str = "") -> Dict[str, Any]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO area_groups (name, description) VALUES ($1,$2) RETURNING *",
            name, description,
        )
        return dict(row)


async def update_area_group(group_id: int, **fields) -> Optional[Dict[str, Any]]:
    if not fields:
        return None
    set_clauses, params = [], []
    for key, value in fields.items():
        params.append(value)
        set_clauses.append(f"{key} = ${len(params)}")
    params.append(group_id)
    query = f"UPDATE area_groups SET {', '.join(set_clauses)} WHERE id = ${len(params)} RETURNING *"
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(query, *params)
        return dict(row) if row else None


async def delete_area_group(group_id: int) -> bool:
    async with get_pool().acquire() as conn:
        result = await conn.execute("DELETE FROM area_groups WHERE id = $1", group_id)
        return result.endswith("1")


async def list_cameras() -> List[Dict[str, Any]]:
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(
            """SELECT c.*, ag.name as area_group_name
               FROM cameras c
               LEFT JOIN area_groups ag ON ag.id = c.area_group_id
               ORDER BY c.camera_id ASC"""
        )
        return [dict(r) for r in rows]


async def get_camera(camera_id: str) -> Optional[Dict[str, Any]]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """SELECT c.*, ag.name as area_group_name
               FROM cameras c
               LEFT JOIN area_groups ag ON ag.id = c.area_group_id
               WHERE c.camera_id = $1""",
            camera_id,
        )
        return dict(row) if row else None


async def create_camera(camera_id: str, name: str, rtsp_url: str,
                         area_group_id: Optional[int], required_ppe: List[str],
                         enabled: bool = True) -> Dict[str, Any]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO cameras (camera_id, name, rtsp_url, area_group_id, required_ppe, enabled)
               VALUES ($1,$2,$3,$4,$5,$6) RETURNING *""",
            camera_id, name, rtsp_url, area_group_id, required_ppe, enabled,
        )
        return dict(row)


async def update_camera(camera_id: str, **fields) -> Optional[Dict[str, Any]]:
    if not fields:
        return None
    set_clauses, params = [], []
    for key, value in fields.items():
        params.append(value)
        set_clauses.append(f"{key} = ${len(params)}")
    params.append(camera_id)
    query = f"UPDATE cameras SET {', '.join(set_clauses)}, updated_at = now() WHERE camera_id = ${len(params)} RETURNING *"
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(query, *params)
        return dict(row) if row else None


async def delete_camera(camera_id: str) -> bool:
    async with get_pool().acquire() as conn:
        result = await conn.execute("DELETE FROM cameras WHERE camera_id = $1", camera_id)
        return result.endswith("1")


async def log_violation(camera_id: str, camera_name: str, zone: str, track_id: int,
                         violation_type: str, snapshot_path: Optional[str] = None,
                         area_group_id: Optional[int] = None, area_group: Optional[str] = None) -> int:
    now = time.time()
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO violations
               (camera_id, camera_name, zone, area_group_id, area_group, track_id,
                violation_type, snapshot_path, epoch_time)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id""",
            camera_id, camera_name, zone, area_group_id, area_group, track_id,
            violation_type, snapshot_path, now,
        )
        return row["id"]


async def mark_alert_dispatched(violation_id: int):
    async with get_pool().acquire() as conn:
        await conn.execute("UPDATE violations SET alert_dispatched = true WHERE id = $1", violation_id)


async def log_alert_dispatch(violation_id: int, rule_id: Optional[int], channel: str, success: bool):
    async with get_pool().acquire() as conn:
        await conn.execute(
            """INSERT INTO alert_dispatch_log (violation_id, rule_id, channel, success)
               VALUES ($1,$2,$3,$4)""",
            violation_id, rule_id, channel, success,
        )


async def get_violation_by_id(violation_id: int) -> Optional[Dict[str, Any]]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM violations WHERE id = $1", violation_id)
        return dict(row) if row else None


async def get_recent_violations(limit: int = 50, camera_id: Optional[str] = None,
                                 violation_type: Optional[str] = None,
                                 area_group_id: Optional[int] = None) -> List[Dict[str, Any]]:
    query = "SELECT * FROM violations WHERE 1=1"
    params = []
    if camera_id:
        params.append(camera_id)
        query += f" AND camera_id = ${len(params)}"
    if violation_type:
        params.append(violation_type)
        query += f" AND violation_type = ${len(params)}"
    if area_group_id:
        params.append(area_group_id)
        query += f" AND area_group_id = ${len(params)}"
    params.append(limit)
    query += f" ORDER BY epoch_time DESC LIMIT ${len(params)}"

    async with get_pool().acquire() as conn:
        rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]


async def get_compliance_stats(window_hours: int = 24) -> Dict[str, Any]:
    cutoff = time.time() - window_hours * 3600
    async with get_pool().acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM violations WHERE epoch_time >= $1", cutoff)
        by_type = await conn.fetch(
            """SELECT violation_type, COUNT(*) as c FROM violations
               WHERE epoch_time >= $1 GROUP BY violation_type ORDER BY c DESC""", cutoff)
        by_camera = await conn.fetch(
            """SELECT camera_name, COUNT(*) as c FROM violations
               WHERE epoch_time >= $1 GROUP BY camera_name ORDER BY c DESC""", cutoff)
        by_area_group = await conn.fetch(
            """SELECT COALESCE(area_group, 'Unassigned') as area_group, COUNT(*) as c FROM violations
               WHERE epoch_time >= $1 GROUP BY area_group ORDER BY c DESC""", cutoff)
        hourly = await conn.fetch(
            """SELECT date_trunc('hour', to_timestamp(epoch_time)) as hour, COUNT(*) as c
               FROM violations WHERE epoch_time >= $1 GROUP BY hour ORDER BY hour ASC""", cutoff)
        return {
            "window_hours": window_hours,
            "total_violations": total,
            "by_type": [dict(r) for r in by_type],
            "by_camera": [dict(r) for r in by_camera],
            "by_area_group": [dict(r) for r in by_area_group],
            "hourly": [{"hour": r["hour"].isoformat(), "count": r["c"]} for r in hourly],
        }


async def update_camera_status(camera_id: str, camera_name: str, zone: str,
                                connected: bool, last_frame_epoch: float):
    async with get_pool().acquire() as conn:
        await conn.execute(
            """INSERT INTO camera_status (camera_id, camera_name, zone, connected, last_frame_epoch, last_updated)
               VALUES ($1,$2,$3,$4,$5, now())
               ON CONFLICT (camera_id) DO UPDATE SET
                    connected = excluded.connected,
                    last_frame_epoch = excluded.last_frame_epoch,
                    last_updated = now()""",
            camera_id, camera_name, zone, connected, last_frame_epoch,
        )


async def get_camera_statuses() -> List[Dict[str, Any]]:
    async with get_pool().acquire() as conn:
        rows = await conn.fetch("SELECT * FROM camera_status")
        return [dict(r) for r in rows]


async def delete_camera_status(camera_id: str):
    async with get_pool().acquire() as conn:
        await conn.execute("DELETE FROM camera_status WHERE camera_id = $1", camera_id)


async def list_rules(enabled_only: bool = False) -> List[Dict[str, Any]]:
    query = "SELECT * FROM alert_rules"
    if enabled_only:
        query += " WHERE enabled = true"
    query += " ORDER BY id ASC"
    async with get_pool().acquire() as conn:
        rows = await conn.fetch(query)
        return [dict(r) for r in rows]


async def create_rule(name, camera_id, zone, violation_type, min_severity,
                       channels, cooldown_seconds, email_recipients, enabled=True) -> Dict[str, Any]:
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO alert_rules
               (name, camera_id, zone, violation_type, min_severity, channels,
                cooldown_seconds, email_recipients, enabled)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *""",
            name, camera_id, zone, violation_type, min_severity, channels,
            cooldown_seconds, email_recipients, enabled,
        )
        return dict(row)


async def update_rule(rule_id: int, **fields) -> Optional[Dict[str, Any]]:
    if not fields:
        return None
    set_clauses, params = [], []
    for key, value in fields.items():
        params.append(value)
        set_clauses.append(f"{key} = ${len(params)}")
    params.append(rule_id)
    query = f"UPDATE alert_rules SET {', '.join(set_clauses)}, updated_at = now() WHERE id = ${len(params)} RETURNING *"
    async with get_pool().acquire() as conn:
        row = await conn.fetchrow(query, *params)
        return dict(row) if row else None


async def delete_rule(rule_id: int) -> bool:
    async with get_pool().acquire() as conn:
        result = await conn.execute("DELETE FROM alert_rules WHERE id = $1", rule_id)
        return result.endswith("1")
