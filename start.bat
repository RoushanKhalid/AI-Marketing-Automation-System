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

:: ── Install / verify dependencies ─────────────────────────────────
echo  [1/4] Installing dependencies...
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo  [WARN] pip reported issues - attempting to continue...
)

:: ── Clear compiled bytecode so new code always runs ───────────────
echo  [2/4] Clearing cached bytecode...
for /d /r "app" %%d in (__pycache__) do (
    if exist "%%d" rmdir /s /q "%%d" 2>nul
)

:: ── Launch ────────────────────────────────────────────────────────
echo  [3/4] Starting server...
echo  [4/4] Opening browser in 3 seconds...
echo.
echo  ============================================================
echo   Server  : http://localhost:8000
echo   Web UI  : http://localhost:8000
echo   API Docs: http://localhost:8000/docs
echo   Model   : llama-3.1-8b-instant (Groq)
echo  ============================================================
echo.

:: Open browser after 3-second delay
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:8000"

:: Start the FastAPI server (blocking — keeps window open)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

echo.
echo  Server stopped. Press any key to exit.
pause >nul
