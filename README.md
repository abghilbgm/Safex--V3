# Sentinel — PPE Compliance Detection System

Real-time AI system for RTSP/CCTV PPE compliance detection with a low-latency
WebSocket dashboard, PostgreSQL storage, dynamic camera management, area
groups, and a database-driven alert rules engine.

## What's new: Dynamic Cameras & Area Groups

Cameras are **no longer hardcoded in a config file** — manage everything
from the dashboard's **Cameras** tab:

- **Add a camera**: "+ Add Camera" → enter Camera ID, name, RTSP URL, pick an
  Area Group, choose required PPE. It starts streaming immediately.
- **Edit a camera**: click "Edit" → change name, **RTSP URL**, area group, or
  required PPE. Saving automatically **restarts that camera's stream** with
  the new settings — no other camera is affected, no app restart needed.
- **Refresh a camera**: click "↻ Refresh" to force-reconnect a camera's
  stream without changing any configuration (useful after a network blip).
- **Area Groups**: click "Manage Area Groups" to create groups you define
  (e.g. "Substation", "Kiln Floor", "Loading Dock") and assign cameras to
  them. Live feeds are grouped by area on the Feeds tab, and violations are
  tagged with the area group they occurred in — filterable in both the
  Violations gallery and the Analytics charts.

All of this is backed by PostgreSQL (`cameras` and `area_groups` tables) —
see `ARCHITECTURE.md` for schema details.

## Where to see violation images (unchanged from before)

Every confirmed violation still saves an annotated evidence snapshot to disk,
with only the **path** referenced in PostgreSQL (`violations.snapshot_path`)
— same mechanism as before, now also tagged with the camera's area group.
View images via:
1. **Dashboard → Violation Feed** (thumbnails, click to enlarge)
2. **Dashboard → Violations tab** (full filterable gallery — filter by
   camera, **area group**, or violation type)
3. **Direct URL**: `http://<host>:8080/api/snapshot/{violation_id}`

---

## Quick Start (Docker — recommended)

```bash
cp .env.example .env
docker compose up -d --build
```
Open **http://localhost:8080/** — on first boot, if no cameras exist yet,
two starter cameras + two area groups are seeded automatically from
`app/config.py`'s `SEED_CAMERAS`/`SEED_AREA_GROUPS` (edit those before first
boot, or just add/edit everything from the dashboard afterward — the seed
only runs once, when the `cameras` table is empty).

## Quick Start (local, no Docker)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

docker run -d --name ppe-postgres -e POSTGRES_DB=ppe_compliance \
  -e POSTGRES_USER=ppe_user -e POSTGRES_PASSWORD=ppe_password \
  -p 5432:5432 postgres:16-alpine

python scripts/download_model.py
python -m app.main
```
Then use the dashboard's Cameras tab to add your real cameras.

## Dashboard Tabs

- **Feeds** — live annotated video, grouped by Area Group
- **Violations** — image gallery, filterable by camera / area group / violation type
- **Analytics** — hourly trend, violation-type breakdown, **by-area-group** chart
- **Cameras** — add / edit (incl. RTSP URL) / refresh / delete cameras; manage area groups
- **Rules** — create/edit/delete DB-driven alert rules live

## Camera Management API

```
GET    /api/cameras                    # list (rtsp_url hidden)
GET    /api/cameras/{camera_id}        # full detail incl. rtsp_url (for edit forms)
POST   /api/cameras                    # add a new camera, starts its worker if enabled
PUT    /api/cameras/{camera_id}        # edit name/rtsp_url/area_group/required_ppe/enabled
                                        # -> auto-restarts the worker if rtsp_url/enabled/required_ppe changed
POST   /api/cameras/{camera_id}/refresh # force stream reconnect, no config change
DELETE /api/cameras/{camera_id}        # stops worker, removes camera

GET    /api/area-groups
POST   /api/area-groups
PUT    /api/area-groups/{id}
DELETE /api/area-groups/{id}           # cameras in the group become unassigned
```

## Alert Rules (database-driven, unchanged)

Alert conditions live in `alert_rules` — manage via Dashboard → Rules tab or
`/api/rules`. See `scripts/seed_rules.py` for starter examples.

## Docker Multi-Camera Scaling

The default `docker-compose.yml` runs one `ppe-app` container handling every
camera in the DB. All camera add/edit/refresh/delete operations work the
same regardless of how many containers you run. For very large camera
counts, you can run a second container instance and split via `PPE_CAMERA_IDS`
env var (still supported as a filter) — see `ARCHITECTURE.md`.

## Power BI

See `powerbi/POWERBI_SETUP.md`. `powerbi/build_powerbi_dataset.py` now also
exports `cameras.csv` and `area_groups.csv` for building area-based reports.

## Project Structure

```
ppe_compliance_system/
├── ARCHITECTURE.md
├── app/
│   ├── config.py               # model/alert-channel tunables + first-boot SEED_CAMERAS/SEED_AREA_GROUPS
│   ├── db.py                     # PostgreSQL: cameras, area_groups, violations, alert_rules
│   ├── camera_manager.py          # dynamic camera worker lifecycle: start/stop/refresh
│   ├── stream_handler.py, detector.py, compliance_engine.py
│   ├── rules_engine.py, alert_manager.py, ws_hub.py
│   └── main.py                     # FastAPI: cameras/area-groups/rules CRUD, WS, snapshot serving
├── dashboard/                        # SPA: Feeds (grouped), Violations, Analytics, Cameras, Rules
├── scripts/                           # download_model, train, seed_rules, quick_test
├── powerbi/                            # CSV extractor (incl. cameras/area_groups) + setup guide
├── requirements.txt, Dockerfile, docker-compose.yml, .env.example
```

## Notes

- Decision-support tool — keep human review in the loop for disciplinary actions.
- Fine-tune the model on your own footage (`scripts/train.py`) for best accuracy.
- Ensure camera footage usage complies with your organization's privacy policies.
