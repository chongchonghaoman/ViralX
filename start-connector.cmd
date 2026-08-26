@echo off
setlocal
cd /d "%~dp0"

if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" connector.py
  goto :end
)

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 connector.py
  goto :end
)

python connector.py

:end
if not %errorlevel%==0 (
  echo.
  echo ViralX Connector failed to start. Review the error shown above.
  echo If Python reports a missing module, install dependencies with:
  echo   python -m pip install -r requirements.txt
  pause
)
endlocal
