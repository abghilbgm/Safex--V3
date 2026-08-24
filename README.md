# Sentinel — PPE Compliance Detection System

Real-time AI system for RTSP/CCTV PPE compliance detection with a low-latency
WebSocket dashboard, PostgreSQL storage, dynamic camera management with area
groups, and a database-driven alert rules engine.

This build comes **pre-loaded with your 16 real plant cameras** (see
`app/config.py` → `SEED_CAMERAS`), automatically grouped into 9 area groups:
Substation, MCC, SYLOC, Pumphouse, Yard, Gates & Security, Safety,
Facilities, and Process. These are seeded into the database automatically
the very first time the app starts.

---

# ⚠️ READ THIS FIRST

This guide assumes a **fresh Windows PC** with nothing installed yet
(matches a typical plant PC). Follow the steps **in order**, top to bottom.
Do not skip a step even if you think it's already done — check the "Verify"
line under each step before moving to the next one.

Estimated total time: 30–45 minutes for first-time setup.

---

## STEP 0 — What you need before starting

| Requirement | Why |
|---|---|
| Windows 10/11 PC with internet access (temporarily, for downloads) | to install Python, PostgreSQL, and download the AI model |
| Admin rights on the PC | to install software |
| Network access to your camera IPs (`192.169.0.65` and `192.168.100.65`) | to actually stream video |
| This project folder (unzipped) | the actual application |

---

## STEP 1 — Install Python 3.11

1. Go to https://www.python.org/downloads/ and download **Python 3.11.x**
   (do NOT use 3.13 yet — some AI libraries lag behind).
2. Run the installer. **On the first screen, check the box "Add python.exe
   to PATH"** at the bottom before clicking Install.
3. Finish the installation.

**Verify:** Open Command Prompt (`Win + R`, type `cmd`, Enter) and run:
```
python --version
```
You should see `Python 3.11.x`. If you see an error, close and reopen
Command Prompt (PATH changes need a fresh window), or re-run the installer
and make sure "Add to PATH" was checked.

---

## STEP 2 — Install PostgreSQL

1. Go to https://www.postgresql.org/download/windows/ and download the
   PostgreSQL installer (via EnterpriseDB), version 16.
2. Run the installer:
   - Keep the default install directory.
   - Keep all components checked (PostgreSQL Server, pgAdmin 4, Command Line Tools).
   - **Set a password for the `postgres` superuser** — write it down, you'll
     need it in Step 4. (Example used in this guide: `postgres123`)
   - Keep the default port `5432`.
   - Keep the default locale.
3. Let the installation finish (a few minutes). You can skip "Stack Builder"
   at the end (click Cancel/Finish).

**Verify:** Open Command Prompt and run:
```
"C:\Program Files\PostgreSQL\16\bin\psql.exe" --version
```
You should see `psql (PostgreSQL) 16.x`.

---

## STEP 3 — Extract the project

1. Extract the project ZIP to a simple path with no spaces, e.g.:
   ```
   C:\ppe_compliance_system\
   ```
2. Open Command Prompt and navigate into it:
   ```
   cd C:\ppe_compliance_system
   ```

**Verify:** run `dir` — you should see folders `app`, `dashboard`,
`scripts`, `powerbi`, and files `requirements.txt`, `README.md`, etc.

---

## STEP 4 — Create the PostgreSQL database

1. Open Command Prompt in the project folder (`C:\ppe_compliance_system`).
2. Connect to PostgreSQL as the superuser (it will ask for the password you
   set in Step 2):
   ```
   "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres
   ```
3. At the `postgres=#` prompt, run these three commands **one at a time**,
   pressing Enter after each (each must end with a semicolon `;`):
   ```sql
   CREATE DATABASE ppe_compliance;
   CREATE USER ppe_user WITH PASSWORD 'ppe_password';
   GRANT ALL PRIVILEGES ON DATABASE ppe_compliance TO ppe_user;
   ```
4. Type `\q` and press Enter to exit.

> 🔒 **Security note:** `ppe_password` is a placeholder. For a real
> deployment, change it to something stronger, and update `.env` (Step 6)
> to match.

**Verify:** run this and enter `ppe_password` when prompted — if it
connects without error, the database is ready:
```
"C:\Program Files\PostgreSQL\16\bin\psql.exe" -U ppe_user -d ppe_compliance -h localhost
```
Type `\q` to exit.

---

## STEP 5 — Set up the Python environment

In Command Prompt, inside `C:\ppe_compliance_system`:
```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
This downloads all required packages (FastAPI, OpenCV, YOLO/Ultralytics,
PostgreSQL driver, etc.) — this step can take 5–10 minutes depending on
your internet speed.

**Verify:** your Command Prompt line should now start with `(.venv)`.
Run `pip show ultralytics` — it should print package details, not an error.

> ⚠️ Every time you open a **new** Command Prompt window to work on this
> project, you must run `.venv\Scripts\activate` again first.

---

## STEP 6 — Configure environment variables

1. Copy the example env file:
   ```
   copy .env.example .env
   ```
2. Open `.env` in Notepad:
   ```
   notepad .env
   ```
3. At minimum, confirm these match what you set in Step 4:
   ```
   POSTGRES_HOST=localhost
   POSTGRES_PORT=5432
   POSTGRES_DB=ppe_compliance
   POSTGRES_USER=ppe_user
   POSTGRES_PASSWORD=ppe_password
   ```
4. (Optional, can do later) Fill in `PPE_TEAMS_WEBHOOK` and/or
   `PPE_SMTP_*` fields if you already have a Teams webhook URL or SMTP
   credentials for email alerts. You can skip this for now and add it later
   — the app runs fine without alerts configured, violations still get
   logged and shown on the dashboard either way.
5. Save and close Notepad.

> Your 16 camera RTSP URLs do **NOT** need to go in this `.env` file — they
> are already built into `app/config.py` (`SEED_CAMERAS`) and will be loaded
> into the database automatically the first time the app starts (Step 8).

**Verify:** run `type .env` and confirm the POSTGRES_* lines are correct.

---

## STEP 7 — Get a PPE detection AI model

You have two options. **Option A is faster** — use it to get running today,
then switch to Option B later if you want higher accuracy on your specific
cameras/lighting.

### Option A — Download a ready-made model (recommended to start)
```
python scripts\download_model.py
```
This downloads a pretrained YOLOv8 PPE model to `models\best.pt`.

**Verify:**
```
python -c "from ultralytics import YOLO; print(YOLO('models/best.pt').names)"
```
This should print a dictionary of class names like `{0: 'Hardhat', 1:
'Mask', 2: 'NO-Hardhat', ...}`. If any of these names differ from what's
listed in `app/config.py`'s `CLASS_MAP`, add the missing mapping there
(see the comments in that file for the exact format).

### Option B — Train your own model on your plant's footage (better accuracy, do this later)
See the `scripts\train.py` instructions inside the file itself. Requires
annotated footage from your actual cameras — skip this for the initial proof.

---

## STEP 8 — First run (this seeds your 16 cameras automatically)

With your virtual environment still active (`(.venv)` visible in the prompt):
```
python -m app.main
```

**What you should see in the terminal**, in this order:
```
INFO ... PostgreSQL pool ready (localhost:5432/ppe_compliance)
INFO ... No cameras found in DB - seeding from config.SEED_CAMERAS
INFO ... Seeded 16 camera(s) and 9 area group(s)
INFO ... Loading PPE model from models/best.pt on device=cpu
INFO ... [CAM01] worker started (area_group=Substation)
INFO ... [CAM01] connecting to rtsp://admin:mngr%402025@192.169.0.65:554/...
INFO ... [CAM02] worker started (area_group=MCC)
...
INFO ... Reconciled 16 camera(s) from DB (16 started)
INFO:     Uvicorn running on http://0.0.0.0:8080
```

If a camera's network isn't reachable yet, you'll see repeated
`connection failed, retrying in 5s` for that camera — that's expected and
harmless; it will connect automatically the moment the network path is
available, and every other camera keeps working independently.

**Leave this Command Prompt window open** — closing it stops the app.

---

## STEP 9 — Open the dashboard

On the same PC (or any PC on the same network), open a web browser and go to:
```
http://localhost:8080/
```
(Replace `localhost` with the PC's actual IP address, e.g.
`http://192.168.x.x:8080/`, if opening from a different machine.)

You should see the **Sentinel** dashboard with:
- A **Feeds** tab showing your cameras' live video, grouped by area
  (Substation, MCC, SYLOC, Pumphouse, Yard, Gates & Security, Safety,
  Facilities, Process)
- A **Cameras** tab listing all 16 cameras with their connection status
- A **Rules** tab (empty until Step 10)

**Verify:** Click through to the **Cameras** tab — you should see all 16
camera IDs (CAM01–CAM16) listed with their correct area groups.

---

## STEP 10 — Add starter alert rules (optional but recommended)

Open a **second** Command Prompt window (leave the first one running the
app), navigate to the project folder, activate the venv, and run:
```
cd C:\ppe_compliance_system
.venv\Scripts\activate
python scripts\seed_rules.py
```
This creates 3 starter rules: alert on any missing helmet, alert on any
missing vest, and an escalated Teams+email rule for the Substation area.

**Verify:** Refresh the dashboard, go to the **Rules** tab — you should see
3 rules listed. Edit/add more anytime from this tab — no restart needed.

---

## STEP 11 — Confirm detection is actually working

1. Go to the **Feeds** tab and check that at least one camera shows a live
   video feed (not stuck on "Connecting…").
2. Walk a person (with/without a helmet) in front of that camera, or wait
   for one to naturally pass by.
3. Within a few seconds, you should see a **red box** appear around them if
   PPE is missing, and an entry appear in the **Violation Feed** sidebar
   with a thumbnail image.
4. Click that thumbnail to confirm the full-size snapshot opens correctly.

If a camera never connects, see **Troubleshooting** below.

---

## STEP 12 — Keep it running permanently (Windows Task Scheduler)

Right now, the app only runs while your Command Prompt window is open. To
make it start automatically and run in the background permanently:

1. Close the running app (`Ctrl+C` in its Command Prompt window, or just
   close the window).
2. Double-click `run_server.bat` once manually to confirm it still starts
   correctly standalone (it re-activates the venv itself).
3. Open **Task Scheduler** (search for it in the Start Menu).
4. Click **Create Task** (not "Create Basic Task"):
   - **General tab**: Name it `Sentinel PPE System`. Select "Run whether
     user is logged on or not". Check "Run with highest privileges".
   - **Triggers tab**: New → Begin the task **"At startup"**.
   - **Actions tab**: New → Action "Start a program" →
     - Program/script: `wscript.exe`
     - Add arguments: `"C:\ppe_compliance_system\run_server_hidden.vbs"`
   - **Conditions tab**: Uncheck "Start the task only if the computer is on
     AC power" (important for always-on operation).
   - Click OK, enter the Windows account password if prompted.
5. Test it: right-click the new task → **Run**. Wait ~15 seconds, then open
   `http://localhost:8080/` in a browser to confirm it's up.

**Verify:** Restart the PC. After it boots back up, wait a minute, then
check `http://localhost:8080/` loads without you doing anything manually.

---

## STEP 13 — (Optional) Docker-based deployment instead of Steps 1–2, 5, 12

If you'd rather run everything in Docker containers (no manual PostgreSQL
install, no Task Scheduler), skip Steps 1, 2, 5, and 12 above and instead:

1. Install **Docker Desktop for Windows**.
2. In the project folder:
   ```
   copy .env.example .env
   docker compose up -d --build
   ```
3. Wait ~1 minute, then open `http://localhost:8080/` — same dashboard,
   same 16-camera auto-seed on first boot.
4. To seed alert rules: `docker compose exec ppe-app python scripts/seed_rules.py`
5. Docker Desktop's "Restart policy: unless-stopped" (already configured in
   `docker-compose.yml`) means it survives PC reboots automatically — no
   Task Scheduler needed.

---

## Troubleshooting

**A camera never connects (`connection failed, retrying...` forever)**
- Confirm the PC can reach the camera's IP: `ping 192.169.0.65` (or
  `192.168.100.65`). If it times out, it's a network/VLAN issue, not the app.
- Confirm the RTSP URL, username, and password are correct — test with VLC
  Media Player first (Media → Open Network Stream → paste the RTSP URL).
- Special character note: if a password contains `@`, it must be
  URL-encoded as `%40` in the RTSP URL (this is already done correctly for
  CAM01/CAM02 in `app/config.py` — `mngr%402025` = `mngr@2025`).

**Dashboard loads but shows no video / blank tiles**
- Check the first Command Prompt window (running `python -m app.main`) for
  error messages under that camera's ID.
- Try `python scripts\quick_test.py --source "rtsp://..."` with that
  camera's exact URL to isolate whether it's an app issue or a camera/network issue.

**"password authentication failed" when starting the app**
- Your `.env` PostgreSQL password doesn't match what you set in Step 4.
  Re-run Step 4's `psql` commands, or update `.env` to match.

**Port 8080 already in use**
- Another program is using that port. Change `PPE_API_PORT=8080` in `.env`
  to e.g. `8090`, and use that port in the dashboard URL instead.

**Editing a camera's RTSP URL later**
- Do NOT edit `app/config.py` after first boot — it's only read once, when
  the database is empty. Instead: Dashboard → **Cameras** tab → **Edit** →
  change the RTSP URL → Save. The camera's stream restarts automatically
  with the new URL, with zero effect on any other camera.

---

## Dashboard Tabs Reference

- **Feeds** — live annotated video, grouped by Area Group
- **Violations** — image gallery, filterable by camera / area group / violation type
- **Analytics** — hourly trend, violation-type breakdown, by-area-group chart
- **Cameras** — add / edit (incl. RTSP URL) / refresh / delete cameras; manage area groups
- **Rules** — create/edit/delete DB-driven alert rules live

## Camera Management API (for reference / automation)

```
GET    /api/cameras                     # list (rtsp_url hidden)
GET    /api/cameras/{camera_id}         # full detail incl. rtsp_url
POST   /api/cameras                     # add a new camera
PUT    /api/cameras/{camera_id}         # edit -> auto-restarts if rtsp_url/enabled/required_ppe changed
POST   /api/cameras/{camera_id}/refresh # force stream reconnect
DELETE /api/cameras/{camera_id}

GET    /api/area-groups
POST   /api/area-groups
PUT    /api/area-groups/{id}
DELETE /api/area-groups/{id}
```

## Power BI Integration

See `powerbi/POWERBI_SETUP.md`. Quick start:
```
python powerbi\build_powerbi_dataset.py --host localhost --db ppe_compliance --user ppe_user --password ppe_password --out powerbi\powerbi_data
```

## Project Structure

```
ppe_compliance_system/
├── README.md                    <- you are here
├── ARCHITECTURE.md
├── app/
│   ├── config.py                # SEED_CAMERAS (your 16 cameras) + SEED_AREA_GROUPS + tunables
│   ├── db.py                      # PostgreSQL: cameras, area_groups, violations, alert_rules
│   ├── camera_manager.py           # dynamic camera worker lifecycle: start/stop/refresh
│   ├── stream_handler.py, detector.py, compliance_engine.py
│   ├── rules_engine.py, alert_manager.py, ws_hub.py
│   └── main.py                       # FastAPI: cameras/area-groups/rules CRUD, WS, snapshot serving
├── dashboard/                          # SPA: Feeds (grouped), Violations, Analytics, Cameras, Rules
├── scripts/
│   ├── download_model.py, train.py
│   ├── seed_rules.py                     # run once after first boot
│   └── quick_test.py                      # standalone single-camera test, no DB needed
├── powerbi/
├── requirements.txt, Dockerfile, docker-compose.yml, .env.example
├── run_server.bat, run_server_hidden.vbs   # Windows Task Scheduler launchers
```

## Notes

- Decision-support tool — keep human review in the loop for disciplinary actions.
- Fine-tune the model on your own footage (`scripts/train.py`) for best accuracy.
- Ensure camera footage usage complies with your organization's privacy policies.
