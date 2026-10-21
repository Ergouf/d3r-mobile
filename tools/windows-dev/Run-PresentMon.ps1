param([Parameter(Mandatory)][string]$Tag, [int]$Seconds = 40)
$root = 'D:\workspace\Diablo'
$dir = Join-Path $root 'out\windows\diagnostics\driver-9150'
New-Item -ItemType Directory -Force $dir | Out-Null
$csv = Join-Path $dir "$Tag-presentmon.csv"
if (Test-Path -LiteralPath $csv) { Remove-Item -LiteralPath $csv -Force }
& (Join-Path $root 'tools\windows-dev\Get-ActiveDisplayMode.ps1') -AsJson | Set-Content -LiteralPath (Join-Path $dir "$Tag-display.json") -Encoding utf8
$pm = Join-Path $root 'local\tools\PresentMon\PresentMon.exe'
$p = Start-Process -FilePath $pm -ArgumentList @('--process_name','01001B300B9BE000.exe','--output_file',$csv,'--delay','10','--timed',$Seconds,'--qpc_time_ms','--write_display_metadata','--no_console_stats','--stop_existing_session') -PassThru -WindowStyle Hidden
"pm_pid=$($p.Id) csv=$csv"
