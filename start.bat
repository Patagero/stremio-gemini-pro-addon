@echo off
title Slo AI Gemini 3.7 Pro Addon
cd /d "%~dp0"

echo ===================================================
echo   Zaganjam Slo AI Gemini 3.7 Pro Stremio Addon
echo ===================================================
echo.

set "PY_EXE=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe"
if exist "%PY_EXE%" (
    "%PY_EXE%" -m app.main
) else (
    python -m app.main
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [NAPAKA] Zagon ni uspel! Koda napake: %ERRORLEVEL%
)

echo.
pause
