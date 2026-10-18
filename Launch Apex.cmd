@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto :failed
)
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, httpx, webview, websockets" >nul 2>&1
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto :failed
)
".venv\Scripts\python.exe" launch.py %*
if errorlevel 1 goto :failed
exit /b 0
:failed
echo Apex could not start. See the error above.
pause
exit /b 1
