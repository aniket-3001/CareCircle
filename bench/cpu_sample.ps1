param([int]$Seconds = 5)
# Prints CPU use (percent of one core) per python process over a window. Used to find the bottleneck during load tests.
$snap = @{}
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object { $snap[$_.Id] = $_.CPU }
Start-Sleep $Seconds
$rows = @()
Get-Process python -ErrorAction SilentlyContinue | ForEach-Object {
    if ($snap.ContainsKey($_.Id)) {
        $pct = [math]::Round(($_.CPU - $snap[$_.Id]) / $Seconds * 100)
        $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)").CommandLine
        $role = if ($cmd -match 'graphmem.api') { 'API' } elseif ($cmd -match 'http_load') { 'LOADGEN' } elseif ($cmd -match 'multiprocessing') { 'LOADGEN-child' } else { 'other' }
        if ($pct -ge 3) { $rows += [pscustomobject]@{ Role = $role; Pid = $_.Id; CpuPct = $pct } }
    }
}
$rows | Sort-Object Role, Pid | Format-Table -AutoSize | Out-String
