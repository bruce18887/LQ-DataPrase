@echo off
REM ============================================================
REM  LQ-DataPrase Build Script
REM  Builds frontend + backend into a single ready-to-run folder.
REM
REM  Usage:
REM    build.bat          (full build)
REM    build.bat --clean  (clean build from scratch)
REM
REM  All build output (stdout + stderr) is written to build.log
REM  in the project root for easier debugging. High-level progress
REM  is also echoed to the console.
REM ============================================================

setlocal enabledelayedexpansion

set PYTHON=.venv\Scripts\python.exe
set NPM=npm
set DIST_DIR=dist\LQ-DataPrase
set RELEASE_DIR=release
set LOG_FILE=build.log

REM Truncate the log file at the start of each run.
echo Build started %DATE% %TIME% > "%LOG_FILE%"
echo ============================================ >> "%LOG_FILE%"

echo.
echo ============================================================
echo  LQ-DataPrase Build
echo ============================================================
echo.
echo Build log: %LOG_FILE%
echo.

REM ------------------------------------------------------------
REM  Pre-build: kill any running LQ-DataPrase.exe so PyInstaller
REM  can overwrite the dist/ folder (otherwise COLLECT fails with
REM  PermissionError on locked .pyd files).
REM ------------------------------------------------------------
tasklist /FI "IMAGENAME eq LQ-DataPrase.exe" 2>nul | find /I "LQ-DataPrase.exe" >nul
if %ERRORLEVEL% equ 0 (
    echo [pre] Stopping running LQ-DataPrase.exe...
    echo [pre] Stopping running LQ-DataPrase.exe... >> "%LOG_FILE%"
    taskkill /F /IM LQ-DataPrase.exe >> "%LOG_FILE%" 2>&1
)

REM ------------------------------------------------------------
REM  Step 1: Build frontend
REM ------------------------------------------------------------
echo [1/5] Building frontend...
echo [1/5] Building frontend... >> "%LOG_FILE%"
if not exist "frontend\package.json" (
    echo [ERROR] frontend\package.json not found
    echo [ERROR] frontend\package.json not found >> "%LOG_FILE%"
    exit /b 1
)
cd frontend
call %NPM% run build >> "..\%LOG_FILE%" 2>&1
set BUILD_EXIT=!ERRORLEVEL!
cd ..
echo --- End of frontend build output --- >> "%LOG_FILE%"
if !BUILD_EXIT! neq 0 (
    echo [ERROR] Frontend build failed! See %LOG_FILE% for details.
    echo [ERROR] Frontend build failed! >> "%LOG_FILE%"
    exit /b 1
)
echo [1/5] Frontend build OK.
echo [1/5] Frontend build OK. >> "%LOG_FILE%"

REM ------------------------------------------------------------
REM  Step 2: Install PyInstaller
REM ------------------------------------------------------------
echo [2/5] Checking PyInstaller...
echo [2/5] Checking PyInstaller... >> "%LOG_FILE%"
"%PYTHON%" -m pip install --quiet pyinstaller >> "%LOG_FILE%" 2>&1
set BUILD_EXIT=!ERRORLEVEL!
if !BUILD_EXIT! neq 0 (
    echo [ERROR] Failed to install PyInstaller. See %LOG_FILE% for details.
    echo [ERROR] Failed to install PyInstaller. >> "%LOG_FILE%"
    exit /b 1
)

REM ------------------------------------------------------------
REM  Step 3: Build mode
REM
REM  We do NOT delete build/dist directories �� PyInstaller's --noconfirm
REM  flag lets it overwrite in place, which is much faster because the
REM  Analysis cache (build\<name>\Analysis-00.toc) is reused. Only the
REM  changed files are re-collected.
REM
REM  If you hit weird state issues (missing modules, stale .pyd locks),
REM  pass --clean to force a full rebuild:
REM    build.bat --clean
REM ------------------------------------------------------------
if "%1"=="--clean" (
    echo [3/5] Full clean rebuild requested...
    echo [3/5] Full clean rebuild requested... >> "%LOG_FILE%"
    if exist build rmdir /s /q build
    if exist dist rmdir /s /q dist
    if exist %RELEASE_DIR% rmdir /s /q %RELEASE_DIR%
    set PYINSTALLER_CLEAN_FLAG=--clean
) else (
    echo [3/5] Incremental build ^(use --clean for full rebuild^)
    echo [3/5] Incremental build (use --clean for full rebuild) >> "%LOG_FILE%"
    set PYINSTALLER_CLEAN_FLAG=
)

REM ------------------------------------------------------------
REM  Step 4: Run PyInstaller
REM
REM  We use `python -u` (unbuffered) so output is flushed immediately to
REM  the log file — otherwise stdout is block-buffered when redirected to
REM  a file, and the log appears empty until the process exits.
REM ------------------------------------------------------------
echo [4/5] Running PyInstaller...
echo [4/5] Running PyInstaller... >> "%LOG_FILE%"
"%PYTHON%" -u -m PyInstaller lq_dataprase.spec !PYINSTALLER_CLEAN_FLAG! --noconfirm >> "%LOG_FILE%" 2>&1
set BUILD_EXIT=!ERRORLEVEL!
if !BUILD_EXIT! neq 0 (
    echo [ERROR] PyInstaller build failed! See %LOG_FILE% for details.
    echo [ERROR] PyInstaller build failed! >> "%LOG_FILE%"
    exit /b 1
)
echo [4/5] PyInstaller build OK.
echo [4/5] PyInstaller build OK. >> "%LOG_FILE%"

REM ------------------------------------------------------------
REM  Step 5: Assemble release folder
REM ------------------------------------------------------------
echo [5/5] Assembling release folder...
echo [5/5] Assembling release folder... >> "%LOG_FILE%"

REM Copy PyInstaller output
if exist %RELEASE_DIR% rmdir /s /q %RELEASE_DIR%
xcopy /E /I /Q "%DIST_DIR%" "%RELEASE_DIR%" >nul

REM Ensure frontend_dist is present (PyInstaller puts it in _internal)
if not exist "%RELEASE_DIR%\frontend_dist" (
    if exist "%DIST_DIR%\_internal\frontend_dist" (
        echo        Copying frontend_dist from _internal...
        echo        Copying frontend_dist from _internal... >> "%LOG_FILE%"
        xcopy /E /I /Q "%DIST_DIR%\_internal\frontend_dist" "%RELEASE_DIR%\frontend_dist" >nul
    ) else if exist "frontend\dist" (
        echo        Copying frontend_dist from source...
        echo        Copying frontend_dist from source... >> "%LOG_FILE%"
        xcopy /E /I /Q "frontend\dist" "%RELEASE_DIR%\frontend_dist" >nul
    )
)

REM Create empty runtime directories
if not exist "%RELEASE_DIR%\media" mkdir "%RELEASE_DIR%\media"

REM Remove build artifacts to save space
if exist "%RELEASE_DIR%\_internal\include" rmdir /s /q "%RELEASE_DIR%\_internal\include" 2>nul

echo.
echo ============================================================
echo  BUILD COMPLETE
echo ============================================================
echo.
echo  Release folder: %RELEASE_DIR%\
echo  Build log:      %LOG_FILE%
echo.
echo  Contents:
dir /B "%RELEASE_DIR%\LQ-DataPrase.exe" 2>nul && echo    LQ-DataPrase.exe  (main executable)
dir /B "%RELEASE_DIR%\frontend_dist" 2>nul && echo    frontend_dist\    (Vue SPA assets)
dir /B "%RELEASE_DIR%\_internal" 2>nul && echo    _internal\        (Python + dependencies)
echo    media\            (created at runtime)
echo.
echo  To run:
echo    cd %RELEASE_DIR%
echo    LQ-DataPrase.exe
echo.
echo  Default login: admin / admin123
echo  Default port:  http://localhost:8000
echo.
echo  Runtime files (auto-created on first run):
echo    - db.sqlite3   (SQLite database)
echo    - secret.key   (auto-generated secret)
echo    - staticfiles\ (collected static files)
echo ============================================================

echo Build finished %DATE% %TIME% >> "%LOG_FILE%"

endlocal
