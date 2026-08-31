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

for /f "usebackq delims=" %%P in (`powershell.exe -NoProfile -Command "$ErrorActionPreference='SilentlyContinue'; $health=Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2; if ($health.service.id -eq 'viralx-home-worker') { Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8000 -State Listen ^| Select-Object -ExpandProperty OwningProcess -Unique }"`) do (
  echo Replacing existing ViralX Worker process %%P...
  taskkill.exe /PID %%P /T /F >nul 2>nul
  timeout.exe /t 1 /nobreak >nul
)

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
