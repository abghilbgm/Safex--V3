# Sentinel — PPE Compliance Detection System

Real-time AI system for RTSP/CCTV PPE compliance detection: low-latency
WebSocket dashboard, PostgreSQL storage, dynamic camera management with
area groups, and a database-driven alert rules engine.

Pre-loaded with your **16 real plant cameras**, auto-organized into 9 area
groups (Substation, MCC, SYLOC, Pumphouse, Yard, Gates & Security, Safety,
Facilities, Process) — seeded into the database automatically on first boot.

---

## What was fixed (if you hit "Application startup failed. Exiting.")

That generic message from Uvicorn hides the real error. Two things were
added to fix this properly:

1. **`app/db.py`** now **retries** the initial Postgres connection for up
   to 60 seconds (instead of failing on the very first attempt) — this is
   the #1 cause of this error in Docker: the app container can start a few
   seconds before Postgres is fully ready to accept connections.
2. **`app/main.py`** now logs the **full Python traceback** on any startup
   failure, with a clear labeled banner, instead of letting Uvicorn hide it.
3. A new **`scripts/check_db_connection.py`** diagnostic tool lets you test
   your exact database connection in isolation, in 5 seconds, with a plain-
   English explanation of what's wrong if it fails.

If you still hit issues, **run this first**:
```
python scripts/check_db_connection.py
```
(or, in Docker: `docker compose exec ppe-app python scripts/check_db_connection.py`)

---

## Deploy with Docker (your setup: Postgres 14 + Docker)

### Step 1 — Prerequisites
- Docker Desktop installed and running.
- Your camera network reachable from wherever Docker runs (same host/VLAN as `192.169.0.65` and `192.168.100.65`).

### Step 2 — Get the project ready
```bash
cd ppe_compliance_system
cp .env.example .env
```
You do **not** need to edit `.env` for Docker — `docker-compose.yml`
automatically sets `POSTGRES_HOST=postgres` for the app container (the
Postgres container's service name), overriding whatever is in `.env`. This
was the exact class of bug that caused earlier failures: `.env` having
`POSTGRES_HOST=localhost`, which is wrong from *inside* a container.

### Step 3 — Get a PPE detection model
```bash
docker compose run --rm ppe-app python scripts/download_model.py
```
This downloads `models/best.pt`, which is mounted into the container via
the `./models` volume (see `docker-compose.yml`), so it persists across
rebuilds.

### Step 4 — Start everything
```bash
docker compose up -d --build
```
This starts:
- `postgres` (PostgreSQL 14, matching your existing version) — waits until
  its healthcheck passes before...
- `ppe-app` starts (depends_on: postgres healthy) — and internally retries
  its own DB connection for up to 60s as a second layer of protection.

### Step 5 — Watch it start up (first time takes ~10-20 seconds)
```bash
docker compose logs -f ppe-app
```
Expected output, in order:
```
INFO ... Starting up: connecting to database...
INFO ... PostgreSQL pool ready (postgres:5432/ppe_compliance) after 1 attempt(s)
INFO ... No cameras found in DB - seeding from config.SEED_CAMERAS
INFO ... Seeded 16 camera(s) and 9 area group(s)
INFO ... Loading detection model from models/best.pt ...
INFO ... [CAM01] worker started (area_group=Substation)
...
INFO ... Reconciled 16 camera(s) from DB (16 started)
INFO ... Startup complete - application is ready.
INFO:     Uvicorn running on http://0.0.0.0:8080
```
Press `Ctrl+C` to stop watching logs (the containers keep running).

**If it fails here instead:** the full traceback will now print directly in
this log (not just "Application startup failed. Exiting.") — read it, it
will tell you exactly what's wrong. Also run:
```bash
docker compose exec ppe-app python scripts/check_db_connection.py
```

### Step 6 — Open the dashboard
```
http://localhost:8080/
```
Check the **Cameras** tab — you should see all 16 cameras (CAM01–CAM16)
grouped by area.

### Step 7 — Seed starter alert rules (optional)
```bash
docker compose exec ppe-app python scripts/seed_rules.py
```

### Step 8 — Confirm it survives a restart
```bash
docker compose restart
docker compose logs -f ppe-app
```
Should come back up cleanly with the same 16 cameras (they're now in the
Postgres volume, not re-seeded since the table is no longer empty).

---

## Alternative: run locally without Docker (Postgres installed directly)

If you'd rather not use Docker for Postgres:

1. Install PostgreSQL 14 locally, create the database:
   ```sql
   CREATE DATABASE ppe_compliance;
   CREATE USER ppe_user WITH PASSWORD 'ppe_password';
   GRANT ALL PRIVILEGES ON DATABASE ppe_compliance TO ppe_user;
   ```
2. In `.env`, set `POSTGRES_HOST=localhost` (this is already the default).
3. Set up Python:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate        # Windows
   pip install -r requirements.txt
   ```
4. Verify the connection works BEFORE starting the full app:
   ```bash
   python scripts/check_db_connection.py
   ```
5. Get a model and run:
   ```bash
   python scripts/download_model.py
   python -m app.main
   ```

---

## Your 16 Cameras & Area Groups

| Area Group | Cameras |
|---|---|
| Substation | CAM01 |
| MCC | CAM02 |
| SYLOC | CAM03 (SYLOC 2), CAM04 (SYLOC 1) |
| Pumphouse | CAM05, CAM06, CAM07 |
| Yard | CAM08 (Container Yard), CAM16 (Scrap Yard) |
| Gates & Security | CAM09 (AG Gate PTZ), CAM13 (Admin Gate), CAM14 (Admin Entrance), CAM15 (AG Security) |
| Safety | CAM10 (Safety Corner) |
| Facilities | CAM11 (Ahara Bhuvan) |
| Process | CAM12 (Caustic) |

This mapping lives in `app/config.py` (`SEED_CAMERAS` / `SEED_AREA_GROUPS`)
and is only read **once**, when the `cameras` table is empty. After first
boot, manage everything from the dashboard's **Cameras** tab instead —
editing `config.py` again has no effect unless you wipe the database
(`docker compose down -v`, which deletes all data).

---

## Editing a camera's RTSP URL later

**Do NOT edit `app/config.py` after first boot.** Instead:
Dashboard → **Cameras** tab → **Edit** → change the RTSP URL → Save. That
camera's stream restarts automatically with the new URL; every other
camera keeps running untouched.

---

## Dashboard Tabs

- **Feeds** — live annotated video, grouped by Area Group
- **Violations** — image gallery, filterable by camera / area group / violation type
- **Analytics** — hourly trend, violation-type breakdown, by-area-group chart
- **Cameras** — add / edit (incl. RTSP URL) / refresh / delete cameras; manage area groups
- **Rules** — create/edit/delete DB-driven alert rules live

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "Application startup failed. Exiting." | Now shows full traceback instead | Read the traceback in `docker compose logs ppe-app` or your terminal |
| Traceback mentions `InvalidPasswordError` | `.env` password doesn't match Postgres | Run `scripts/check_db_connection.py`; if using Docker with an existing volume, credentials only apply on first init - run `docker compose down -v` to reset (deletes data) |
| Traceback mentions `Connection refused` repeatedly, then gives up after 60s | Postgres never became reachable | `docker compose ps` - is `postgres` healthy? `docker compose logs postgres` |
| Traceback mentions `MODEL FILE NOT FOUND` | Forgot to download a model | `docker compose exec ppe-app python scripts/download_model.py`, then restart: `docker compose restart ppe-app` |
| A specific camera never connects | Network/RTSP issue, not an app bug | `docker compose exec ppe-app python scripts/quick_test.py --source "rtsp://..."` to isolate it |
| Port 8080 already in use | Another program using it | Change `PPE_API_PORT` in `.env`, and the `ports:` mapping in `docker-compose.yml` |

## Camera Management API

```
GET    /api/cameras                     # list (rtsp_url hidden)
GET    /api/cameras/{camera_id}         # full detail incl. rtsp_url
POST   /api/cameras                     # add a new camera
PUT    /api/cameras/{camera_id}         # edit -> auto-restarts if rtsp_url/enabled/required_ppe changed
POST   /api/cameras/{camera_id}/refresh # force stream reconnect
DELETE /api/cameras/{camera_id}

GET/POST/PUT/DELETE /api/area-groups
GET/POST/PUT/DELETE /api/rules
```

## Power BI Integration
See `powerbi/` folder. Quick start:
```bash
python powerbi/build_powerbi_dataset.py --host localhost --db ppe_compliance --user ppe_user --password ppe_password --out powerbi/powerbi_data
```

## Project Structure

```
ppe_compliance_system/
├── README.md
├── app/
│   ├── config.py                # SEED_CAMERAS (16 cameras) + SEED_AREA_GROUPS + tunables
│   ├── db.py                      # PostgreSQL + connection RETRY logic (the startup fix)
│   ├── camera_manager.py           # dynamic camera worker lifecycle
│   ├── stream_handler.py, detector.py, compliance_engine.py
│   ├── rules_engine.py, alert_manager.py, ws_hub.py
│   └── main.py                       # FastAPI + full-traceback startup logging (the startup fix)
├── dashboard/                          # SPA: Feeds, Violations, Analytics, Cameras, Rules
├── scripts/
│   ├── check_db_connection.py           # NEW: run this first if startup fails
│   ├── download_model.py, train.py
│   ├── seed_rules.py, quick_test.py
├── powerbi/
├── requirements.txt, Dockerfile, docker-compose.yml, .env.example
├── run_server.bat, run_server_hidden.vbs   # local (non-Docker) Windows launchers
```

## Notes
- Decision-support tool — keep human review in the loop for disciplinary actions.
- Fine-tune the model on your own footage (`scripts/train.py`) for best accuracy.
- Ensure camera footage usage complies with your organization's privacy policies.
