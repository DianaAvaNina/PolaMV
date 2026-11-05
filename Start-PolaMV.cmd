@echo off
cd /d "%~dp0"
if exist "dist\PolaMV Studio\PolaMV Studio.exe" (
  start "" "dist\PolaMV Studio\PolaMV Studio.exe"
) else (
  ".venv\Scripts\pythonw.exe" run_polamv.py
)
