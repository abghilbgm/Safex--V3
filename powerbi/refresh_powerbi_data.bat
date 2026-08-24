@echo off
cd /d %~dp0\..
call .venv\Scripts\activate.bat
python powerbi\build_powerbi_dataset.py --host localhost --port 5432 --db ppe_compliance --user ppe_user --password ppe_password --out powerbi\powerbi_data
