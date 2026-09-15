@echo off
rem Build the add-in in Release and stage a self-contained distribution folder.
rem Output: dist\DataPrase-AddIn\ (32/64-bit xll + Core.dll + install/uninstall scripts + README)
rem NOTE: keep this file ASCII-only and CRLF-terminated; cmd.exe reads the console codepage,
rem       so UTF-8 Chinese here would come out garbled. Chinese guidance lives in install.ps1
rem       (UTF-8 with BOM, read correctly by PowerShell).
setlocal enabledelayedexpansion

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" (
  echo [ERROR] vswhere.exe not found. Visual Studio 2022 is required.
  exit /b 1
)

set "MSBUILD="
for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.Component.MSBuild -find MSBuild\**\Bin\MSBuild.exe`) do set "MSBUILD=%%i"
if not defined MSBUILD (
  echo [ERROR] MSBuild.exe not found.
  exit /b 1
)

set "ROOT=%~dp0.."
set "BIN=%ROOT%\src\DataPrase.AddIn\bin\Release"
set "OUT=%ROOT%\dist\DataPrase-AddIn"

pushd "%ROOT%"
"%MSBUILD%" DataPrase-ExcelAddin.sln -t:Restore,Build -p:Configuration=Release -v:m -nologo
if errorlevel 1 (echo [ERROR] build failed & popd & exit /b 1)
popd

if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%"

copy /y "%BIN%\DataPrase.AddIn-AddIn-packed.xll"    "%OUT%\DataPrase-AddIn32.xll" >nul
copy /y "%BIN%\DataPrase.AddIn-AddIn64-packed.xll"  "%OUT%\DataPrase-AddIn64.xll" >nul
copy /y "%BIN%\DataPrase.Core.dll"                  "%OUT%\DataPrase.Core.dll"    >nul
copy /y "%~dp0install.ps1"                          "%OUT%\install.ps1"          >nul
copy /y "%~dp0uninstall.ps1"                        "%OUT%\uninstall.ps1"        >nul

> "%OUT%\README.txt" (
  echo LQ-DataPrase Excel Add-in
  echo.
  echo Install for the current user ^(no admin^):
  echo   powershell -ExecutionPolicy Bypass -File install.ps1
  echo   ^(or right-click install.ps1 -^> Run with PowerShell^)
  echo.
  echo Uninstall:
  echo   powershell -ExecutionPolicy Bypass -File uninstall.ps1
  echo.
  echo What the installer does:
  echo   * Picks DataPrase-AddIn32.xll or DataPrase-AddIn64.xll by the local Excel bitness,
  echo     copies it plus DataPrase.Core.dll into %%APPDATA%%\Microsoft\AddIns\DataPrase\,
  echo     and registers it under HKCU\Software\Microsoft\Office\^<ver^>\Excel\Options.
  echo   * Restart Excel afterwards; a "DataPrase" tab appears on the ribbon.
  echo   * Requires .NET Framework 4.6.2 ^(built into Win10/11^). No VSTO runtime needed.
)

echo.
echo Packaged to: %OUT%
dir /b "%OUT%"
