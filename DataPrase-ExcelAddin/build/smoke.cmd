@echo off
rem Double-clickable smoke test: loads the built .xll into Excel and checks =DpPing().
rem Keep this window open to read the result.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0smoke-register-xll.ps1"
echo.
echo Exit code: %ERRORLEVEL%
pause
