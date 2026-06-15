@echo off
REM ============================================================
REM  LQ-DataPrase Build Script
REM  Packages the application as a standalone Windows executable.
REM
REM  Usage:
REM    build.bat          (full build)
REM    build.bat --clean  (clean build from scratch)
REM ============================================================

setlocal enabledelayedexpansion

set PYTHON=.venv\Scripts\python.exe
set DIST_DIR=dist\LQ-DataPrase

echo.
echo ============================================================
echo  LQ-DataPrase Standalone Build
echo ============================================================
echo.

REM Check Python venv
if not exist "%PYTHON%" (
    echo [ERROR] Python venv not found at %PYTHON%
    echo         Run: python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements\base.txt
    exit /b 1
)

REM Install/upgrade build dependencies
echo [1/4] Installing build dependencies...
"%PYTHON%" -m pip install --quiet pyinstaller
if errorlevel 1 (
    echo [ERROR] Failed to install PyInstaller
    exit /b 1
)

REM Clean previous build (if --clean flag)
if "%1"=="--clean" (
    echo [2/4] Cleaning previous build...
    if exist build rmdir /s /q build
    if exist dist rmdir /s /q dist
    if exist *.spec.bak del /q *.spec.bak
) else (
    echo [2/4] Skipping clean (use --clean to force)
)

REM Run PyInstaller
echo [3/4] Running PyInstaller...
"%PYTHON%" -m PyInstaller lq_dataprase.spec --clean --noconfirm 2>&1
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed!
    exit /b 1
)

REM Copy templates and assets that PyInstaller may have missed
echo [4/4] Post-build cleanup...

REM Ensure the frontend_dist is in the output
if not exist "%DIST_DIR%\frontend_dist" (
    echo [WARN] frontend_dist not found in output, copying manually...
    xcopy /E /I /Q "frontend\dist" "%DIST_DIR%\frontend_dist" >nul
)

REM Create media directory
if not exist "%DIST_DIR%\media" mkdir "%DIST_DIR%\media"

echo.
echo ============================================================
echo  BUILD COMPLETE
echo ============================================================
echo.
echo  Output: %DIST_DIR%\LQ-DataPrase.exe
echo.
echo  To run:
echo    cd %DIST_DIR%
echo    LQ-DataPrase.exe
echo.
echo  Default login: admin / admin123
echo  Default port:  http://localhost:8000
echo.
echo  Files created at runtime:
echo    - db.sqlite3   (SQLite database)
echo    - media/       (uploaded files)
echo    - secret.key   (auto-generated secret)
echo ============================================================

endlocal
