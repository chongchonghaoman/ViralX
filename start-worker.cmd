@echo off
setlocal
cd /d "%~dp0"

set "VIRALX_ALLOWED_ORIGINS=https://viralx.metrolabs.mobi"
set "VIRALX_WORKER_HOST=127.0.0.1"
set "VIRALX_WORKER_PORT=8000"
set "VIRALX_MAX_CONCURRENT=1"
set "VIRALX_RATE_LIMIT_ANALYSES=6"
set "VIRALX_RATE_WINDOW_SECONDS=3600"
set "VIRALX_RETENTION_HOURS=24"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop-viralx-worker.ps1" -ProjectRoot "%~dp0."
if errorlevel 1 (
  echo Unable to replace the existing ViralX Worker safely.
  exit /b 1
)
"%SystemRoot%\System32\timeout.exe" /t 1 /nobreak >nul

if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" worker_server.py
  goto :done
)

py -3 worker_server.py

:done
if errorlevel 1 (
  echo.
  echo ViralX Worker failed to start. Install dependencies with:
  echo   python -m pip install -r requirements.txt
  pause
)
endlocal
