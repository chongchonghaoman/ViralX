@echo off
setlocal
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-worker.ps1"
if errorlevel 1 (
  echo.
  echo ViralX Worker failed to start. Install dependencies with:
  echo   python -m pip install -r requirements.txt
  pause
)
endlocal
