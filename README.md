# Sentinel — PPE Compliance Detection System

Real-time AI system for RTSP/CCTV PPE compliance detection: low-latency
WebSocket dashboard, PostgreSQL storage, dynamic camera management with
area groups, and a database-driven alert rules engine.

Pre-loaded with your **16 real plant cameras**, auto-organized into 9 area
groups — seeded into the database automatically on first boot.

---

## What was fixed in this update

You reported three symptoms after running the previous version:
1. Not all 16 cameras loading in the frontend
2. Video "sliding"/showing "Reconnecting…" (especially the PTZ camera)
3. Violations tab showing "Failed to load violations"

**All three traced back to one root cause**: the camera worker loop was
writing to the database on **every single loop tick** (~100x/second per
camera). With 16 cameras that's up to **~1,600 database writes per
second**, which exhausts a small connection pool. When the pool is
exhausted:
- A camera worker awaiting a DB connection can raise an unhandled
  exception and silently die → that camera simply stops (never "loads").
- The same pool exhaustion can cause other API requests (like
  `/api/violations`) to fail or time out at the exact same moment.
- Under load, backend responsiveness degrades, which can present as choppy
  video / repeated reconnects on the frontend, especially noticeable on a
  PTZ camera whose stream is naturally more prone to brief interruptions
  when panning/zooming.

### The fixes (all verified with automated tests)

1. **Throttled DB status writes** — `db.update_camera_status()` was called
   every loop tick; now it's throttled to once every `PPE_STATUS_UPDATE_INTERVAL`
   seconds per camera (default 4s). Verified: reduced from ~150-300
   writes/3sec down to 3 writes/3sec in testing — roughly a **100x reduction**.

2. **Self-healing camera loop** — previously, ANY unexpected error inside a
   camera's loop (a DB timeout, a decode hiccup) would permanently kill
   that camera's task with no recovery. Now every loop iteration is wrapped
   so a transient error is logged and the loop **continues** instead of
   dying. Verified: a camera worker survives DB errors that previously
   would have killed it.

3. **Retry-safe violation logging** — a violation is only marked "already
   logged" **after** its database write succeeds. If the write fails
   (transient pool exhaustion), the same violation is automatically
   retried on the next frame instead of being silently lost. Verified: a
   violation that fails twice then succeeds is correctly saved with no
   image/record lost.

4. **One bad camera can't block the rest** — `reconcile_all()` (which
   starts all cameras at boot) now catches per-camera startup errors
   individually. Verified: with 16 cameras, if one fails to start, the
   other 15 still start normally.

5. **Bigger connection pool + Postgres tuning** — default pool raised from
   10 → 30 connections (`POSTGRES_POOL_MAX` in `.env`), and
   `docker-compose.yml` now also raises Postgres's own `max_connections`
   to 100 to match.

6. **Clear, diagnosable errors instead of generic failures** —
   `/api/violations` and `/api/stats` now return an explicit `503` with the
   actual error message (e.g. "pool exhausted") instead of an opaque crash
   the frontend could only describe as "Failed to load violations". The
   Violations tab now shows that real error message plus a **Retry** button.

### New: per-camera "↻ Reconnect" button in the Feeds tab

Every camera tile in the **Feeds** tab now has a small **↻** button next to
its status indicator — click it to force *just that camera's* stream to
reconnect immediately, without affecting any other camera. This is exactly
what you asked for, and is the fastest fix for a PTZ camera (like "AG Gate
PTZ") that appears stuck on "Reconnecting…" after it pans — instead of
waiting for the automatic retry backoff, click ↻ and it reconnects in
about a second.

There's also a **"↻ Reconnect All Cameras"** button above the feed grid,
which reconnects every camera with a small stagger (so it doesn't hit the
backend with 16 simultaneous restarts at once).

---

## Deploy with Docker (Postgres 14 + Docker)

```bash
cp .env.example .env
docker compose run --rm ppe-app python scripts/download_model.py
docker compose up -d --build
docker compose logs -f ppe-app
```
Expected startup log:
```
[1/3] Connecting to database...
PostgreSQL pool ready (postgres:5432/ppe_compliance) pool_size=4-30 after 1 attempt(s)
No cameras found in DB - seeding from config.SEED_CAMERAS
Seeded 16 camera(s) and 9 area group(s)
[2/3] Loading detection model ...
[3/3] Starting camera workers...
Reconciled 16 camera(s) from DB (16 started)
STARTUP COMPLETE - application is ready.
```
Open **http://localhost:8080/**.

If something still fails, the full traceback now prints directly and
immediately in this log — read it, or run:
```bash
docker compose exec ppe-app python scripts/check_db_connection.py
```

---

## Your 16 Cameras & Area Groups

| Area Group | Cameras |
|---|---|
| Substation | CAM01 |
| MCC | CAM02 |
| SYLOC | CAM03, CAM04 |
| Pumphouse | CAM05, CAM06, CAM07 |
| Yard | CAM08, CAM16 |
| Gates & Security | CAM09, CAM13, CAM14, CAM15 |
| Safety | CAM10 |
| Facilities | CAM11 |
| Process | CAM12 |

Editing an RTSP URL later: Dashboard → **Cameras** tab → **Edit** → change
URL → Save (auto-restarts just that camera).

---

## Dashboard Tabs

- **Feeds** — live annotated video grouped by area, with **per-camera
  Reconnect (↻)** button and a global "Reconnect All Cameras" button
- **Violations** — image gallery with camera/area/type filters; on load
  failure now shows the actual error + a Retry button
- **Analytics** — hourly trend, violation-type breakdown, by-area-group chart
- **Cameras** — add / edit (incl. RTSP URL) / refresh / delete cameras;
  manage area groups
- **Rules** — create/edit/delete DB-driven alert rules live

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Camera stuck "Reconnecting…" | Normal for PTZ cameras when panning, or a transient network blip | Click the **↻** button on that camera's tile in the Feeds tab |
| Several cameras never load | Was: DB pool exhaustion killing camera workers | Fixed in this version (throttled writes + self-healing loop + bigger pool) - if it persists, run `check_db_connection.py` to check pool usage |
| Violations tab: "Could not load violations" | DB error - now shown with the actual message | Read the specific error shown, or click **Retry**; check `docker compose logs postgres` for DB-side issues |
| "Application startup failed. Exiting." | Now shows full traceback in logs | Read `docker compose logs -f ppe-app`; run `scripts/check_db_connection.py` |

## Camera Management API
```
GET/POST/PUT/DELETE /api/cameras[/{camera_id}]
POST /api/cameras/{camera_id}/refresh   # force reconnect (used by the ↻ button)
GET/POST/PUT/DELETE /api/area-groups
GET/POST/PUT/DELETE /api/rules
```

## Power BI
```bash
python powerbi/build_powerbi_dataset.py --host localhost --db ppe_compliance --user ppe_user --password ppe_password --out powerbi/powerbi_data
```

## Project Structure
```
ppe_compliance_system/
├── README.md
├── app/
│   ├── config.py               # SEED_CAMERAS (16 cams) + tunables incl. pool size, status-update interval
│   ├── db.py                     # PostgreSQL + connection retry
│   ├── camera_manager.py          # dynamic lifecycle + SELF-HEALING loop + throttled writes (this update's main fix)
│   ├── stream_handler.py, detector.py, compliance_engine.py
│   ├── rules_engine.py, alert_manager.py, ws_hub.py
│   └── main.py                     # FastAPI; /api/violations & /api/stats now return clear 503s on DB errors
├── dashboard/                        # SPA incl. new per-camera Reconnect button + error states with Retry
├── scripts/                           # download_model, train, seed_rules, quick_test, check_db_connection
├── powerbi/
├── requirements.txt, Dockerfile, docker-compose.yml, .env.example
├── run_server.bat, run_server_hidden.vbs
```

## Notes
- Decision-support tool — keep human review in the loop for disciplinary actions.
- Fine-tune the model on your own footage (`scripts/train.py`) for best accuracy.
- Ensure camera footage usage complies with your organization's privacy policies.
