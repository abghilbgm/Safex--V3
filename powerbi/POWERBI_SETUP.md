# Power BI Integration Guide

## Option 1 — CSV Folder connector (simplest)
```
python powerbi\build_powerbi_dataset.py --host localhost --db ppe_compliance --user ppe_user --password ppe_password --out powerbi\powerbi_data
```
Produces violations.csv, daily_summary.csv, camera_status.csv, alert_rules.csv,
cameras.csv, area_groups.csv. Power BI Desktop: Get Data -> Folder.

## Option 2 — Live REST API
- http://<host>:8080/api/violations?limit=5000&area_group_id={id}
- http://<host>:8080/api/stats?window_hours=24 (includes by_area_group)

## Option 3 — Native PostgreSQL connector (recommended)
Get Data -> PostgreSQL database. Tables: violations, cameras, area_groups,
alert_rules, alert_dispatch_log.

## Viewing violation images in Power BI
snapshot_path -> http://<host>:8080/api/snapshot/{id}. Add as calculated
column, set Image data category.
