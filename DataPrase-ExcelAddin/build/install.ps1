# Install the LQ-DataPrase Excel add-in for the current user (no admin required).
# Detects Excel bitness, copies the matching .xll + DataPrase.Core.dll, and registers it
# under HKCU\Software\Microsoft\Office\<ver>\Excel\Options (the standard XLL add-in slot).
param(
    [string]$SourceDir = $PSScriptRoot
)

$ErrorActionPreference = 'Stop'

function Get-ExcelPlatform {
    $c2r = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Office\ClickToRun\Configuration' -ErrorAction SilentlyContinue
    if ($c2r -and $c2r.Platform) { return $c2r.Platform }   # "x86" | "x64"

    $appPath = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe' -ErrorAction SilentlyContinue
    if (-not $appPath) { throw 'Excel 未安装或未注册（找不到 excel.exe）。' }

    $exe = $appPath.'(default)'
    if ($exe -like '*Program Files (x86)*') { return 'x86' }
    return 'x64'
}

function Get-ExcelVersionKey {
    $versions = Get-ChildItem 'HKCU:\Software\Microsoft\Office' -ErrorAction SilentlyContinue |
        Where-Object { $_.PSChildName -match '^\d+\.\d+$' -and (Test-Path (Join-Path $_.PSPath 'Excel')) } |
        Sort-Object { [version]$_.PSChildName } -Descending
    if (-not $versions) { throw '未找到 Excel 的注册表项（请先启动一次 Excel）。' }
    return $versions[0].PSChildName
}

$platform = Get-ExcelPlatform
$xllName = if ($platform -eq 'x86') { 'DataPrase-AddIn32.xll' } else { 'DataPrase-AddIn64.xll' }
Write-Output "Excel 位数: $platform  ->  $xllName"

$sourceXll = Join-Path $SourceDir $xllName
$sourceCore = Join-Path $SourceDir 'DataPrase.Core.dll'
if (-not (Test-Path $sourceXll)) { throw "找不到 $sourceXll" }
if (-not (Test-Path $sourceCore)) { throw "找不到 $sourceCore" }

$targetDir = Join-Path $env:APPDATA 'Microsoft\AddIns\DataPrase'
New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
Copy-Item $sourceXll $targetDir -Force
Copy-Item $sourceCore $targetDir -Force
$installedXll = Join-Path $targetDir $xllName

$version = Get-ExcelVersionKey
$optionsPath = "HKCU:\Software\Microsoft\Office\$version\Excel\Options"
if (-not (Test-Path $optionsPath)) { New-Item -Path $optionsPath -Force | Out-Null }

# Already registered?
$existing = Get-ItemProperty $optionsPath -ErrorAction SilentlyContinue
foreach ($prop in $existing.PSObject.Properties) {
    if ($prop.Name -like 'OPEN*' -and ("$($prop.Value)" -like '*DataPrase*')) {
        Write-Output "已注册（$($prop.Name)），更新路径。"
        Set-ItemProperty -Path $optionsPath -Name $prop.Name -Value ('/R "' + $installedXll + '"')
        Write-Output "完成：$installedXll"
        exit 0
    }
}

# Find the first free OPEN slot (OPEN, OPEN1, OPEN2, ...)
$slot = 'OPEN'
$index = 0
while ((Get-ItemProperty -Path $optionsPath -Name $slot -ErrorAction SilentlyContinue)) {
    $index++
    $slot = "OPEN$index"
}

Set-ItemProperty -Path $optionsPath -Name $slot -Value ('/R "' + $installedXll + '"')
Write-Output "已注册到 Excel $version 的 $slot 项。"
Write-Output "完成：$installedXll"
Write-Output "请重启 Excel，应出现 “DataPrase” 选项卡。"
