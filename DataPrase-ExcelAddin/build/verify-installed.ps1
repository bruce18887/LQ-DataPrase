# Verify what a *real* Excel startup actually loads, without asking a human to click.
# Launches a hidden Excel instance (which processes the HKCU ...Excel\Options OPEN slots
# exactly like the user's Excel), then reads back facts through the add-in's own functions.
# Run:  powershell -ExecutionPolicy Bypass -File build\verify-installed.ps1
param(
    [string]$XllPath,
    [string]$Csv
)

$ErrorActionPreference = 'Stop'
$excel = $null
$wb = $null
$failed = $false

function Step($label, $script) {
    try {
        $value = & $script
        Write-Output ("{0,-28} {1}" -f $label, $value)
        return $value
    } catch {
        Write-Output ("{0,-28} ERROR: {1}" -f $label, $_.Exception.Message)
        $script:failed = $true
        return $null
    }
}

try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    # Automation must not be interactive: the add-in suppresses its own MessageBox when
    # Application.Interactive is false, which is what keeps Run('DpExpRefresh') from blocking.
    try { $excel.Interactive = $false } catch { Write-Output "Interactive=false refused: $($_.Exception.Message)" }

    # --- What did Excel load at startup from the registered OPEN slot? ---
    $openSlots = @()
    foreach ($ver in (Get-ChildItem 'HKCU:\Software\Microsoft\Office' |
            Where-Object { $_.PSChildName -match '^\d+\.\d+$' })) {
        $opt = "HKCU:\Software\Microsoft\Office\$($ver.PSChildName)\Excel\Options"
        if (Test-Path $opt) {
            $props = Get-ItemProperty $opt -ErrorAction SilentlyContinue
            foreach ($p in $props.PSObject.Properties) {
                if ($p.Name -like 'OPEN*') { $openSlots += "$($p.Name)=$($p.Value)" }
            }
        }
    }
    Write-Output "OPEN slots: $(if ($openSlots) { $openSlots -join ' | ' } else { '(none)' })"

    # A loaded XLL shows up as a hidden workbook in the Workbooks collection.
    Step "startup workbooks" {
        $names = @($excel.Workbooks | ForEach-Object { $_.Name })
        if ($names) { $names -join ', ' } else { '(none)' }
    }

    Step "startup DpPing" {
        $probe = $excel.Workbooks.Add()
        try {
            $probe.Worksheets.Item(1).Range('A1').Formula = '=DpPing()'
            [string]$probe.Worksheets.Item(1).Range('A1').Value2
        } finally { $probe.Close($false) }
    }

    if ($XllPath) {
        $resolved = (Resolve-Path -LiteralPath $XllPath).Path
        Write-Output "RegisterXLL: $([bool]$excel.RegisterXLL($resolved))  ($resolved)"
        Step "DpPing after RegisterXLL" {
            $probe = $excel.Workbooks.Add()
            try {
                $probe.Worksheets.Item(1).Range('A1').Formula = '=DpPing()'
                [string]$probe.Worksheets.Item(1).Range('A1').Value2
            } finally { $probe.Close($false) }
        }
    }

    # --- Does the real ExpControls.Build produce the whole panel, in the right rows? ---
    # DpSelfCheck runs the production Build on a throwaway workbook and reports facts.
    # (Not routed through Step: assigning a function's output would swallow the label line.)
    $selfCheck = try { [string]$excel.Run('DpSelfCheck') } catch { "ERROR: $($_.Exception.Message)" }
    Write-Output 'DpSelfCheck ->'
    Write-Output $selfCheck
    if ($selfCheck -notmatch 'controls=16/16 landed=16/16 onaction=16/16 captions=15/15') {
        Write-Output 'SELF_CHECK_MISMATCH: expected controls=16/16 landed=16/16 onaction=16/16 captions=15/15'
        $failed = $true
    }

    # --- End-to-end: real datalog through the production processing chain ---
    if ($Csv) {
        $flow = try { [string]$excel.Run('DpSelfCheckFlow', $Csv) } catch { "ERROR: $($_.Exception.Message)" }
        Write-Output 'DpSelfCheckFlow ->'
        Write-Output $flow
        if ($flow -notmatch 'panel=16/16' -or $flow -notmatch 'allSiteSum=[1-9]') {
            Write-Output 'FLOW_MISMATCH: expected panel=16/16 and a non-zero allSiteSum'
            $failed = $true
        }
    } else {
        Write-Output 'DpSelfCheckFlow: SKIPPED (pass -Csv <datalog copy> to run the end-to-end check)'
    }

    # --- Can Excel resolve the [ExcelCommand] macro name a Form Control's OnAction uses? ---
    # Same name-resolution path OnAction relies on; a miss throws "macro not found".
    Step "Run('DpExpRefresh')" { $excel.Run('DpExpRefresh'); 'resolved (ran, no error)' }

    # --- Does AddFormControl + caption/OnAction round-trip on a live sheet? ---
    $probeWb = $excel.Workbooks.Add()
    try {
        $ws = $probeWb.Worksheets.Item(1)
        $shape = $ws.Shapes.AddFormControl(7, 48, 30, 120, 15)   # xlCheckBox
        Step "AddFormControl shape" { $shape.Name }
        Step "shape.OnAction assign" { $shape.OnAction = 'DpExpRefresh'; [string]$shape.OnAction }
        Step "shape.ControlFormat.Value" {
            $shape.ControlFormat.Value = 1
            [string]$shape.ControlFormat.Value
        }
        $shape.Delete()
    } finally { $probeWb.Close($false) }
} catch {
    Write-Output "VERIFY_FAILED: $($_.Exception.Message)"
    $failed = $true
} finally {
    if ($wb) { try { $wb.Close($false) } catch { } }
    if ($excel) {
        try { $excel.Quit() } catch { }
        try { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) } catch { }
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

if ($failed) { exit 1 }
Write-Output 'VERIFY_DONE'
