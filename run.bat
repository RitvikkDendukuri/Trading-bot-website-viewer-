@echo off
title Trading Bots — Local Server
cd /d "%~dp0"
echo.
echo  ========================================
echo   Trading Bots — Local Server
echo   http://localhost:8080
echo  ========================================
echo.
echo  Press Ctrl+C to stop.
echo.
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
pause
