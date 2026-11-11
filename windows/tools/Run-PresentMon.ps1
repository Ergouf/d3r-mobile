param([Parameter(Mandatory)][string]$Tag, [int]$Seconds = 40, [int]$ProcessId = 0, [switch]$Wait)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$dir = Join-Path $root 'out\windows\diagnostics\driver-9150'
New-Item -ItemType Directory -Force $dir | Out-Null
$csv = Join-Path $dir "$Tag-presentmon.csv"
if (Test-Path -LiteralPath $csv) { Remove-Item -LiteralPath $csv -Force }
& (Join-Path $root 'windows\tools\Get-ActiveDisplayMode.ps1') -AsJson | Set-Content -LiteralPath (Join-Path $dir "$Tag-display.json") -Encoding utf8
$pm = Join-Path $root 'local\tools\PresentMon\PresentMon.exe'
$gameExe = 'D:\Games\DiabloIII\01001B300B9BE000\01001B300B9BE000.exe'
if ($ProcessId -eq 0) {
    $gameMatches = @(Get-Process -Name '01001B300B9BE000' | Where-Object { $_.Path -eq $gameExe })
    if ($gameMatches.Count -ne 1) { throw 'Specify the single game process to capture.' }
    $ProcessId = $gameMatches[0].Id
}
$gameProcess = Get-Process -Id $ProcessId
if ($gameProcess.Path -ne $gameExe) { throw 'The selected process is not the installed game.' }
@{ pid=$gameProcess.Id; exe=$gameProcess.Path; started=([datetimeoffset]$gameProcess.StartTime).ToString('o');
   sha256=(Get-FileHash -LiteralPath $gameExe).Hash; seconds=$Seconds; delay=3 } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $dir "$Tag-identity.json") -Encoding utf8
$p = Start-Process -FilePath $pm -ArgumentList @('--process_id', $ProcessId, '--output_file', ('"'+$csv+'"'),
    '--session_name', "SNX-$Tag-$PID", '--delay','3','--timed',$Seconds,'--terminate_after_timed',
    '--terminate_on_proc_exit','--qpc_time_ms','--write_display_metadata','--no_console_stats','--no_track_input') -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $dir "$Tag-stdout.log") -RedirectStandardError (Join-Path $dir "$Tag-stderr.log")
"pm_pid=$($p.Id) csv=$csv"
if ($Wait) {
    [void]$p.Handle
    if (-not $p.WaitForExit(($Seconds + 15) * 1000)) { throw "PresentMon did not finish: pid=$($p.Id)" }
    if ($p.ExitCode -ne 0) { throw "PresentMon failed: exit=$($p.ExitCode)" }
    if (-not (Test-Path -LiteralPath $csv) -or (Get-Item -LiteralPath $csv).Length -eq 0) { throw 'PresentMon produced no CSV.' }
}
