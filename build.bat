@echo off
REM ============================================================
REM  LQ-DataPrase Build Script
REM  Builds frontend + backend into Windows installer and portable ZIP.
REM
REM  Output: out/LQ-DataPrase-<version>-Setup.exe
REM          out/LQ-DataPrase-<version>-win.zip
REM ============================================================

setlocal enabledelayedexpansion

REM ------------------------------------------------------------
REM  Pre-build: kill any running instances of the app so output
REM  directories can be safely removed and overwritten. On Windows,
REM  the previous build's output is often locked by antivirus,
REM  search indexer, or leftover Electron/Python child processes.
REM ------------------------------------------------------------
echo [pre] Stopping any running LQ-DataPrase.exe instances...
taskkill /F /IM LQ-DataPrase.exe >nul 2>&1
taskkill /F /IM electron.exe /T >nul 2>&1
taskkill /F /IM python.exe /T >nul 2>&1

REM Give Windows a moment to release file handles (AV/indexer).
echo [pre] Waiting for file handles to release...
timeout /t 3 /nobreak >nul

REM ------------------------------------------------------------
REM  Mark build output dirs as "not content indexed" so Windows
REM  Search (WSearch) never opens freshly written exe files — that
REM  lock made electron-builder's rcedit fail with "Unable to commit
REM  changes" (WinError 5) on the ~188 MB main exe. Attribute is
REM  persistent; harmless if already set.
REM ------------------------------------------------------------
attrib +I out >nul 2>&1
attrib +I dist >nul 2>&1
attrib +I build >nul 2>&1

REM ------------------------------------------------------------
REM  Clean previous build output so electron-builder never hits
REM  "The process cannot access the file because it is being used
REM  by another process" on stale out/ folders.
REM ------------------------------------------------------------
echo [pre] Removing previous build output...
if exist "out\" (
    rmdir /s /q "out" >nul 2>&1
    if %ERRORLEVEL% neq 0 (
        echo [pre] WARNING: Could not remove out\ — retrying in 5s...
        timeout /t 5 /nobreak >nul
        rmdir /s /q "out" >nul 2>&1
    )
)
if exist "out-build\" (
    rmdir /s /q "out-build" >nul 2>&1
)
if exist "dist\LQ-DataPrase\" (
    rmdir /s /q "dist\LQ-DataPrase" >nul 2>&1
)
echo [pre] Cleanup done.

REM ------------------------------------------------------------
REM  Run the unified npm build pipeline.
REM ------------------------------------------------------------
call npm run dist:win

endlocal
