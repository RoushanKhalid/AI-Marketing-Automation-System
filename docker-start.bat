@echo off
title AI Marketing Automation System - Docker Startup

echo.
echo  ============================================================
echo   AI Marketing Automation System - Docker Startup
echo  ============================================================
echo.

:: ── Move to the project root (where this .bat lives) ──────────────
cd /d "%~dp0"

:: ── Check Docker CLI availability ─────────────────────────────────
docker --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Docker CLI not found. Please install Docker Desktop and try again.
    pause
    exit /b 1
)

:: ── Prefer modern Docker Compose, fallback to legacy docker-compose ─
set "DOCKER_CMD=docker compose"
%DOCKER_CMD% version >nul 2>&1
if errorlevel 1 (
    set "DOCKER_CMD=docker-compose"
    %DOCKER_CMD% version >nul 2>&1
    if errorlevel 1 (
        echo  [ERROR] Docker Compose not found. Install Docker Compose or update Docker Desktop.
        pause
        exit /b 1
    )
)

:: ── Check .env ────────────────────────────────────────────────────
if not exist ".env" (
    echo  [ERROR] .env file not found!
    echo         Please create .env with: GROQ_API_KEY=your_key_here
    pause
    exit /b 1
)

echo  [1/1] Starting application in Docker...
echo.
echo  ============================================================
echo   Access the app at: http://localhost:8000
echo   API Docs at:     http://localhost:8000/docs
echo  ============================================================
echo.

%DOCKER_CMD% up --build --detach
if errorlevel 1 (
    echo.
    echo  [ERROR] Docker Compose failed to start the application.
    pause
    exit /b 1
)

echo  [OK] Application started in Docker.
echo  Opening browser to http://localhost:8000...
start "" cmd /c "timeout /t 5 /nobreak >nul & start http://localhost:8000"

echo.
echo  To view live logs, run: %DOCKER_CMD% logs -f app
pause >nul
