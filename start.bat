@echo off
title AI Marketing Automation System

echo.
echo  ============================================================
echo   AI Marketing Automation System
echo  ============================================================
echo.

:: ── Move to the project root (where this .bat lives) ──────────────
cd /d "%~dp0"

:: ── Check Python ──────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Please install Python 3.10+
    pause
    exit /b 1
)

:: ── Check .env ────────────────────────────────────────────────────
if not exist ".env" (
    echo  [ERROR] .env file not found!
    echo         Please create .env with: GROQ_API_KEY=your_key_here
    pause
    exit /b 1
)

:: ── Clear port 8000 if already in use ──────────────────────────────
echo  [1/5] Clearing port 8000 if occupied...
set "PORT_KILLED=0"
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do (
    echo  [WARN] Found process %%p listening on port 8000.
    taskkill /PID %%p /F >nul 2>&1
    if errorlevel 1 (
        echo  [ERROR] Could not stop PID %%p. Please free port 8000 manually.
        pause
        exit /b 1
    )
    set "PORT_KILLED=1"
)
if "%PORT_KILLED%"=="1" (
    echo  [OK] Port 8000 cleared.
) else (
    echo  [OK] Port 8000 is free.
)

:: ── Install / verify dependencies ─────────────────────────────────
echo  [2/5] Installing dependencies...
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo  [WARN] pip reported issues - attempting to continue...
)

:: ── Clear compiled bytecode so new code always runs ───────────────
echo  [3/5] Clearing cached bytecode...
for /d /r "app" %%d in (__pycache__) do (
    if exist "%%d" rmdir /s /q "%%d" 2>nul
)

:: ── Launch ────────────────────────────────────────────────────────
echo  [4/5] Starting server...
echo  [5/5] Opening browser in 3 seconds...
echo.
echo  ============================================================
echo   Server  : http://localhost:8000
echo   Web UI  : http://localhost:8000
echo   API Docs: http://localhost:8000/docs
echo  ============================================================
echo.

:: Open browser after 3-second delay
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:8000"

:: Start the FastAPI server (blocking — keeps window open)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

echo.
echo  Server stopped. Press any key to exit.
pause >nul
