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
REM  Usage (from package.json): scripts\electron-builder.cmd --win [--dir]
REM ============================================================
setlocal
for /L %%i in (1,1,4) do (
  call npx electron-builder --config electron-builder.yml %*
  if not errorlevel 1 exit /b 0
  echo [builder] attempt %%i/4 failed - waiting 20s for file locks to clear...
  timeout /t 20 /nobreak >nul
)
echo [builder] electron-builder failed after 4 attempts
exit /b 1
