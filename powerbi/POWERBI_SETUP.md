# Power BI Integration Guide

## Option 1 — CSV Folder connector (simplest)
```bash
python powerbi/build_powerbi_dataset.py --host localhost --db ppe_compliance --user ppe_user --password ppe_password --out powerbi/powerbi_data
```
Produces `violations.csv`, `daily_summary.csv`, `camera_status.csv`,
`alert_rules.csv`, `cameras.csv`, `area_groups.csv`.
Power BI Desktop: **Get Data → Folder** → select `powerbi/powerbi_data`.
Schedule `powerbi/refresh_powerbi_data.bat` in Task Scheduler to refresh.

## Option 2 — Live REST API
- `http://<host>:8080/api/violations?limit=5000&area_group_id={id}`
- `http://<host>:8080/api/stats?window_hours=24` (includes `by_area_group`)
- `http://<host>:8080/api/cameras`, `http://<host>:8080/api/area-groups`

## Option 3 — Native PostgreSQL connector (recommended)
**Get Data → PostgreSQL database** → tables: `violations`, `cameras`,
`area_groups`, `alert_rules`, `alert_dispatch_log`. Join `violations.area_group_id`
to `area_groups.id` for live area-based reporting, or `cameras.area_group_id`
to see current (not historical) assignments.

## Viewing violation images in Power BI
Each row's `snapshot_path` corresponds to `http://<host>:8080/api/snapshot/{id}`.
Add a calculated column with that URL and set Power BI's Image data category.

## Suggested Report Layout
- KPI cards: total violations (24h/7d), cameras offline, active rules, area groups count
- Trend line: violations by hour/day, split by violation_type
- Bar chart: violations **by area group** (new) and by camera
- Table with image column: recent violations + snapshot thumbnail
- Rule audit: join `alert_dispatch_log` → `alert_rules`
