# Sentinel — PPE Compliance Detection System

Real-time AI system for RTSP/CCTV PPE compliance detection: low-latency
WebSocket dashboard, PostgreSQL storage, dynamic camera management with
area groups, and a database-driven alert rules engine.

Pre-loaded with your **16 real plant cameras**, auto-organized into 9 area
groups — synced into the database automatically on every app startup.

---

## Fix: "cameras from config.py not showing in the frontend"

If you upgraded from an older build and your database only ended up with a
few cameras (e.g. just CAM02) instead of all 16, here's why and how to fix
it - **no reinstall or data loss required**.

### Why this happens
`app/config.py` is only a **seed list** — cameras are copied from it into
PostgreSQL, and the frontend only ever reads from PostgreSQL, never from
the Python file directly. In an older version, if the seeding process was
interrupted partway (app crashed, container restarted mid-seed, etc.), any
camera that hadn't been created yet was **permanently skipped** on future
restarts. This build fixes that.

### The fix
`sync_seed_data()` (in `app/db.py`) now runs automatically on **every**
app startup, and separately checks **each individual camera**: if a camera
from `config.py` is missing from the database, it gets created. If it
already exists, it's left completely untouched. This makes it self-healing
— no matter how partial the database state is, restarting the app tops it
up automatically.

### How to fix it right now, 3 ways (easiest first)

**Option A — Dashboard button (recommended):**
Open the dashboard → **Cameras** tab → click **"⟲ Sync Default Cameras"**.
You'll see a confirmation like "Added 15 missing camera(s): CAM01, CAM03, ...".
The Feeds tab will now show all 16.

**Option B — Just restart the app:**
```bash
docker compose restart ppe-app
docker compose logs -f ppe-app
```
Look for this line near the top of the logs:
```
[ppe.db] Seed sync: X area group(s) created, Y camera(s) created, Z already existed
```

**Option C — API call directly:**
```bash
curl -X POST http://localhost:8080/api/cameras/sync-seed
```
Then verify:
```bash
curl -s http://localhost:8080/api/cameras | python3 -c "import sys,json; print(len(json.load(sys.stdin)))"
```
Should print `16`.

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
PostgreSQL pool ready ...
[ppe.db] Seed sync: 9 area group(s) created, 16 camera(s) created, 0 already existed
[2/3] Loading detection model ...
[3/3] Starting camera workers...
Reconciled 16 camera(s) from DB (16 started)
STARTUP COMPLETE - application is ready.
```
Open **http://localhost:8080/**.

If startup fails, the full traceback now prints directly in this log. Also try:
```bash
docker compose exec ppe-app python scripts/check_db_connection.py
```
This tells you exactly how many cameras are in the DB right now, and
reminds you to run the sync if any are missing.

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

**Editing an RTSP URL later:** Dashboard → **Cameras** tab → **Edit** →
change URL → Save (auto-restarts just that camera).

---

## Dashboard Tabs

- **Feeds** — live annotated video grouped by area, with per-camera
  Reconnect (↻) button and a global "Reconnect All Cameras" button
- **Violations** — image gallery with camera/area/type filters; shows the
  actual error + Retry button if loading fails
- **Analytics** — hourly trend, violation-type breakdown, by-area-group chart
- **Cameras** — add/edit/refresh/delete cameras; manage area groups;
  **"⟲ Sync Default Cameras"** button to top up any missing seed cameras
- **Rules** — create/edit/delete DB-driven alert rules live

## Other Reliability Fixes in This Build

- Throttled DB status writes (was every loop tick per camera, now once
  every few seconds) — prevents connection pool exhaustion with many cameras
- Self-healing camera loop — a transient error no longer permanently kills
  a camera's worker
- Retry-safe violation logging — a violation that fails to save is retried
  on the next frame instead of being lost
- One camera failing to start no longer blocks the other 15 from starting
- `/api/violations` and `/api/stats` return a clear error message on DB
  failure instead of a generic "Failed to load"

## Camera Management API
```
GET/POST/PUT/DELETE /api/cameras[/{camera_id}]
POST /api/cameras/{camera_id}/refresh   # force reconnect
POST /api/cameras/sync-seed              # top up missing seed cameras
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
│   ├── config.py               # SEED_CAMERAS (16 cams) + SEED_AREA_GROUPS + tunables
│   ├── db.py                     # PostgreSQL + sync_seed_data() (the missing-cameras fix)
│   ├── camera_manager.py          # dynamic lifecycle, self-healing loop, throttled writes
│   ├── stream_handler.py, detector.py, compliance_engine.py
│   ├── rules_engine.py, alert_manager.py, ws_hub.py
│   └── main.py                     # FastAPI incl. POST /api/cameras/sync-seed
├── dashboard/                        # SPA incl. "Sync Default Cameras" + per-camera Reconnect buttons
├── scripts/                           # download_model, train, seed_rules, quick_test, check_db_connection
├── powerbi/
├── requirements.txt, Dockerfile, docker-compose.yml, .env.example
├── run_server.bat, run_server_hidden.vbs
```

## Notes
- Decision-support tool — keep human review in the loop for disciplinary actions.
- Fine-tune the model on your own footage (`scripts/train.py`) for best accuracy.
- Ensure camera footage usage complies with your organization's privacy policies.
