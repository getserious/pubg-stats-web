@echo off
setlocal
cd /d "%~dp0"
title GAME.GG Configuration Check
if exist ".venv\Scripts\python.exe" goto :check_python
where py >nul 2>nul
if errorlevel 1 goto :use_python
py -3 -m venv .venv
if errorlevel 1 goto :failed
goto :check_python
:use_python
where python >nul 2>nul
if errorlevel 1 goto :no_python
python -m venv .venv
if errorlevel 1 goto :failed
:check_python
".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 goto :broken_env
".venv\Scripts\python.exe" -c "from dotenv import dotenv_values" >nul 2>nul
if not errorlevel 1 goto :diagnose
echo [SETUP] Installing python-dotenv in the same environment as GAME.GG...
".venv\Scripts\python.exe" -m pip --version >nul 2>nul
if not errorlevel 1 goto :install_dotenv
".venv\Scripts\python.exe" -m ensurepip --upgrade
if errorlevel 1 goto :failed
:install_dotenv
".venv\Scripts\python.exe" -m pip install "python-dotenv>=1.0"
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -c "from dotenv import dotenv_values" >nul 2>nul
if errorlevel 1 goto :failed
:diagnose
".venv\Scripts\python.exe" -u check_config.py
if errorlevel 1 goto :failed
goto :done
:no_python
echo [ERROR] Python 3.10 or newer is required. Install Python, then retry.
goto :done
:broken_env
echo [ERROR] This project's .venv does not run or uses Python older than 3.10.
echo If this folder was copied from another PC, remove ONLY the .venv folder and retry.
echo Keep .env and cache.sqlite3.
goto :done
:failed
echo.
echo [ERROR] Setup or diagnosis failed. Keep this window open and read the message above.
echo If installation failed, check your Internet connection and retry.
:done
echo.
pause
