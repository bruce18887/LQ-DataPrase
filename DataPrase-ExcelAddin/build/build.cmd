@echo off
rem Build the LQ-DataPrase Excel add-in (x86 + x64 packed .xll).
rem Uses VS2022 MSBuild; no .NET SDK required (classic csproj + NuGet reference assemblies).
setlocal enabledelayedexpansion

set "CONFIG=%~1"
if "%CONFIG%"=="" set "CONFIG=Debug"

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if not exist "%VSWHERE%" (
  echo [ERROR] vswhere.exe not found. Visual Studio 2022 is required.
  exit /b 1
)

set "MSBUILD="
for /f "usebackq tokens=*" %%i in (`"%VSWHERE%" -latest -products * -requires Microsoft.Component.MSBuild -find MSBuild\**\Bin\MSBuild.exe`) do set "MSBUILD=%%i"
if not defined MSBUILD (
  echo [ERROR] MSBuild.exe not found via vswhere.
  exit /b 1
)

set "ROOT=%~dp0.."
pushd "%ROOT%"

echo Using MSBuild: %MSBUILD%
"%MSBUILD%" DataPrase-ExcelAddin.sln -t:Restore,Build -p:Configuration=%CONFIG% -v:m -nologo
set "RC=%ERRORLEVEL%"

popd
exit /b %RC%
