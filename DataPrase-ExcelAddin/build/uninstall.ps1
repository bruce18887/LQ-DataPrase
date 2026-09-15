# Remove the LQ-DataPrase Excel add-in registration (and the copied files) for the current user.
$ErrorActionPreference = 'Stop'

$targetDir = Join-Path $env:APPDATA 'Microsoft\AddIns\DataPrase'

$versions = Get-ChildItem 'HKCU:\Software\Microsoft\Office' -ErrorAction SilentlyContinue |
    Where-Object { $_.PSChildName -match '^\d+\.\d+$' }
$removed = 0

foreach ($ver in $versions) {
    $optionsPath = "HKCU:\Software\Microsoft\Office\$($ver.PSChildName)\Excel\Options"
    if (-not (Test-Path $optionsPath)) { continue }

    $props = (Get-ItemProperty $optionsPath -ErrorAction SilentlyContinue).PSObject.Properties |
        Where-Object { $_.Name -like 'OPEN*' -and ("$($_.Value)" -like '*DataPrase*') }

    foreach ($prop in $props) {
        Remove-ItemProperty -Path $optionsPath -Name $prop.Name -ErrorAction SilentlyContinue
        Write-Output "已移除 Excel $($ver.PSChildName) 的 $($prop.Name)"
        $removed++
    }
}

if ($removed -eq 0) { Write-Output '未找到已注册的 DataPrase 加载项。' }

if (Test-Path $targetDir) {
    Remove-Item $targetDir -Recurse -Force
    Write-Output "已删除 $targetDir"
}

Write-Output '卸载完成（重启 Excel 生效）。'
