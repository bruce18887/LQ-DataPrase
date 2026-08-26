@echo off
REM ============================================================
REM  electron-builder retry wrapper.
REM
REM  electron-builder writes the ~188 MB LQ-DataPrase.exe and then
REM  immediately runs rcedit to set version strings + icon. Windows
REM  Defender / Search indexer briefly locks the freshly written file
REM  (WinError 5 "Unable to commit changes"), which flakes the build.
REM  This wrapper retries the whole packaging step with a backoff so
REM  the lock has time to clear, instead of failing the npm chain.
REM
REM  Dependency layout (single install):
REM  electron + electron-builder live ONLY in frontend\node_modules.
REM  This wrapper therefore:
REM    1. resolves electron-builder from frontend\node_modules\.bin
REM    2. passes -c.electronVersion=<version of the electron package
REM       installed in frontend> — electron-builder normally derives the
REM       version from <cwd>\node_modules\electron, but the repo root no
REM       longer has its own node_modules\electron.
REM
REM  Usage (from package.json): scripts\electron-builder.cmd --win [--dir]
REM ============================================================
setlocal

set "EBIN=%~dp0..\frontend\node_modules\.bin\electron-builder.cmd"
if not exist "%EBIN%" (
  echo [builder] electron-builder not found in frontend\node_modules - run "npm ci" in frontend first
  exit /b 1
)

set "ELECTRON_VERSION="
for /f "usebackq delims=" %%v in (`node -p "require(process.argv[1]).version" "%~dp0..\frontend\node_modules\electron\package.json"`) do set "ELECTRON_VERSION=%%v"
if "%ELECTRON_VERSION%"=="" (
  echo [builder] cannot read electron version from frontend\node_modules\electron\package.json - run "npm ci" in frontend first
  exit /b 1
)

for /L %%i in (1,1,4) do (
  call "%EBIN%" -c.electronVersion=%ELECTRON_VERSION% --config electron-builder.yml %*
  if not errorlevel 1 exit /b 0
  echo [builder] attempt %%i/4 failed - waiting 20s for file locks to clear...
  ping -n 21 127.0.0.1 >nul
  REM (timeout.exe exits immediately when stdin is redirected, so use ping sleep)
)
echo [builder] electron-builder failed after 4 attempts
exit /b 1
