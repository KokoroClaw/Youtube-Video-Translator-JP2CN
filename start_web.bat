@echo off
setlocal
title Kotoba Studio Web UI

cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHON_EXE=%USERPROFILE%\miniconda3\envs\subtitle\python.exe"
set "WEB_URL=http://127.0.0.1:8787"

powershell -NoProfile -Command "try { $response = Invoke-WebRequest -UseBasicParsing -Uri '%WEB_URL%/api/health' -TimeoutSec 2; if ($response.StatusCode -eq 200) { exit 0 } } catch {}; exit 1" >nul 2>&1
if not errorlevel 1 (
    echo Kotoba Studio is already running.
    echo Opening %WEB_URL%
    start "" "%WEB_URL%"
    exit /b 0
)

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Cannot find the subtitle environment:
    echo %PYTHON_EXE%
    echo.
    echo Create it first: conda create -n subtitle python=3.11
    pause
    exit /b 1
)

echo Starting Kotoba Studio...
echo Web UI: %WEB_URL%
echo Close this window to stop the service.
echo.

start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process '%WEB_URL%'"
"%PYTHON_EXE%" web.py

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] Web UI stopped with exit code %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%
