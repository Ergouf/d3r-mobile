param(
  [Parameter(Mandatory)][string]$Tag,
  [Parameter(Mandatory)][string]$Exe,
  [int]$Seconds = 30,
  [string[]]$ProbeArgs = @()
)
$ErrorActionPreference = 'Stop'
$root = 'D:\workspace\Diablo'
$dir = Join-Path $root 'out\windows\diagnostics\driver-9150'
$csv = Join-Path $dir "$Tag-presentmon.csv"
$log = Join-Path $dir "$Tag-probe.log"
$probeCsv = Join-Path $dir "$Tag-probe.csv"
$pm = Join-Path $root 'local\tools\PresentMon\PresentMon.exe'
$exePath = Join-Path $root "out\windows\$Exe"
$exeName = Split-Path $Exe -Leaf
foreach ($f in @($csv, $log, $probeCsv)) { if (Test-Path $f) { Remove-Item -LiteralPath $f -Force } }

$mode = & (Join-Path $root 'windows\tools\Get-ActiveDisplayMode.ps1') -AsJson
$mode | Set-Content -LiteralPath (Join-Path $dir "$Tag-display.json") -Encoding utf8

Start-Process -FilePath $pm -ArgumentList @('--process_name', $exeName, '--output_file', $csv, '--timed', ($Seconds + 12), '--qpc_time_ms', '--write_display_metadata', '--no_console_stats', '--stop_existing_session') -WindowStyle Hidden -PassThru | Out-Null
Start-Sleep -Seconds 3

$probeArgList = @("--seconds=$Seconds", "--output=$probeCsv", '--wait-for-focus') + $ProbeArgs
$p = Start-Process -FilePath $exePath -ArgumentList $probeArgList -PassThru -WindowStyle Normal
$exited = $p.WaitForExit((($Seconds + 40) * 1000))
if (-not $exited) { try { $p.Kill() } catch {}; "PROBE_TIMEOUT" | Add-Content -LiteralPath $log }
"exit_code=$($p.ExitCode)" | Add-Content -LiteralPath $log
Get-Content -LiteralPath $probeCsv -ErrorAction SilentlyContinue | Add-Content -LiteralPath $log

$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
  if (-not (Get-Process -Name 'PresentMon' -ErrorAction SilentlyContinue)) { break }
  Start-Sleep -Milliseconds 500
}
Get-Process -Name 'PresentMon' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

Get-Content -LiteralPath $log
if (Test-Path $csv) { python (Join-Path $root 'windows\tools\analyze_presentmon.py') $csv --skip-seconds 3 --duration-seconds ($Seconds - 3) 2>$null | Out-File -FilePath (Join-Path $dir "$Tag-summary.json") -Encoding utf8 }
