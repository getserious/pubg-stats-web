@echo off
setlocal
cd /d "%~dp0"
title GAME.GG Server
where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] Python 3 is required. Install it from https://www.python.org/downloads/windows/
    pause
    exit /b 1
  )
  set "PY=python"
)
if not exist ".venv\Scripts\python.exe" (
  echo [GAME.GG] Creating a private Python environment...
  %PY% -m venv .venv
  if errorlevel 1 goto :failed
)
echo [GAME.GG] Installing required libraries if needed...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed
if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo [NOTICE] Edit .env and enter your PUBG_API_KEY before searching.
)
echo [GAME.GG] Starting website and Cloudflare together...
echo The local page opens first. The public address opens after DNS/HTTPS checks.
echo Keep this window open. Press Ctrl+C to stop both services.
".venv\Scripts\python.exe" -u run_all.py
if errorlevel 1 goto :failed
pause
exit /b 0
:failed
echo.
echo [ERROR] Setup or server startup failed. Check the messages above.
echo Check your internet connection if library installation failed.
pause
exit /b 1
