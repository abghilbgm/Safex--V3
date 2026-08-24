@echo off
cd /d %~dp0
if not exist ".venv\Scripts\activate.bat" (
    echo Virtual environment not found. Run setup first:
    echo   python -m venv .venv
    echo   .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)
call .venv\Scripts\activate.bat
python -m app.main
