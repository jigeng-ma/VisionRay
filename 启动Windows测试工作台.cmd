@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import pytest, appium, PIL, pytesseract" >nul 2>&1
    if not errorlevel 1 (
        ".venv\Scripts\python.exe" launch.py
        goto :done
    )
)
python launch.py
:done
if errorlevel 1 pause
