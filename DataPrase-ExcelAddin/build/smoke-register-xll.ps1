# Smoke test: load the packed .xll into Excel via COM and verify the add-in responds.
# Default XllPath auto-resolves to the 64-bit Debug build relative to this script,
# so it can be run with no arguments (see smoke.cmd for a double-clickable wrapper).
param(
    [string]$XllPath
)

$ErrorActionPreference = 'Stop'
$excel = $null
$wb = $null

try {
    if (-not $XllPath) {
        $base = Join-Path $PSScriptRoot '..\src\DataPrase.AddIn\bin\Debug'
        $x64 = Join-Path $base 'DataPrase.AddIn-AddIn64-packed.xll'
        $x86 = Join-Path $base 'DataPrase.AddIn-AddIn-packed.xll'
        $XllPath = if (Test-Path -LiteralPath $x64) { $x64 } else { $x86 }
    }

    $resolved = (Resolve-Path -LiteralPath $XllPath).Path
    Write-Output "XLL: $resolved"

    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    try { $excel.AutomationSecurity = 1 } catch { }   # best-effort: avoid macro-block prompts

    $loaded = [bool]$excel.RegisterXLL($resolved)
    Write-Output "RegisterXLL: $loaded"
    if (-not $loaded) { throw "RegisterXLL returned false (add-in failed to load)" }

    $wb = $excel.Workbooks.Add()
    $ws = $wb.Worksheets.Item(1)
    $ws.Range("A1").Formula = "=DpPing()"
    $value = $ws.Range("A1").Value2
    Write-Output "DpPing -> $value"

    if ("$value" -notlike "DataPrase*") { throw "unexpected DpPing value: $value" }

    Write-Output "SMOKE_OK"
}
catch {
    Write-Output "SMOKE_FAILED: $($_.Exception.Message)"
    exit 1
}
finally {
    if ($wb) { try { $wb.Close($false) } catch { } }
    if ($excel) {
        try { $excel.Quit() } catch { }
        try { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) } catch { }
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
