# Run one on-device bring-up probe of the D3 host and collect the evidence.
#
#   pwsh -File d3-android/tools/run_probe.ps1 -Name baseline -Seconds 25
#
# The app data is cleared first because a previous run that ended in an abort or
# a timeout leaves state that wedges the next boot almost immediately (-Keep
# skips that).
#
# Writes logcat-<Name>.txt / d3-crash-<Name>.txt / tombstone-<Name>.txt into
# d3-android/gpu/probe and prints a one-screen summary (log lines, interesting
# markers, crash thread).
param(
    [string]$Name = "baseline",
    [int]$Seconds = 25,
    [switch]$NoAutostart,
    # Clear the app data before the run.  A timed-out or aborted run leaves a
    # partial save under files/runtime and the next boot then wedges in the
    # applet/sync loop within a second, which looks like a fresh bug.  Use
    # -Keep only when the leftover state itself is what is being probed.
    [switch]$Keep
)

$ErrorActionPreference = "Stop"
$pkg = "com.d3mobile.host.recovery"
$activity = "$pkg/com.d3mobile.host.MainActivity"
$outDir = (Resolve-Path (Join-Path $PSScriptRoot "..\gpu\probe")).Path

adb shell am force-stop $pkg | Out-Null
if (-not $Keep) {
    adb logcat -b crash -c | Out-Null
    adb shell pm clear $pkg | Out-Null
}
Start-Sleep -Milliseconds 900
adb logcat -c | Out-Null
adb logcat -b crash -c | Out-Null

if ($NoAutostart) {
    adb shell am start -n $activity | Out-Null
} else {
    adb shell am start -n $activity --ez autostart true | Out-Null
}
$probePid = ""
for ($attempt = 0; $attempt -lt 30; $attempt++) {
    $probePidText = (adb shell pidof $pkg) -join " "
    $probePid = ($probePidText.Trim() -split '\s+')[0]
    if ($probePid -match '^\d+$') { break }
    Start-Sleep -Milliseconds 200
}
if ($probePid -notmatch '^\d+$') {
    throw "No recovery app PID observed; refusing an unfiltered probe capture."
}
Write-Output "probe app pid   : $probePid"
Start-Sleep -Seconds $Seconds

$log = Join-Path $outDir "logcat-$Name.txt"
adb logcat -d --pid=$probePid -s D3Host:* 2>&1 | Set-Content -Encoding UTF8 $log
$gpuLog = Join-Path $outDir "gpu-$Name.txt"
adb logcat -d --pid=$probePid -s d3gpu:* 2>&1 | Set-Content -Encoding UTF8 $gpuLog
$exitInfo = Join-Path $outDir "exit-info-$Name.txt"
adb shell dumpsys activity exit-info $pkg 2>&1 | Set-Content -Encoding UTF8 $exitInfo

$crash = Join-Path $outDir "d3-crash-$Name.txt"
$crashText = adb shell run-as $pkg cat files/d3-crash.txt 2>&1
if ($LASTEXITCODE -eq 0 -and $crashText) { $crashText | Set-Content -Encoding UTF8 $crash }

$tomb = Join-Path $outDir "tombstone-$Name.txt"
adb logcat -b crash -d 2>&1 | Set-Content -Encoding UTF8 $tomb

# Also grab the top of the maps log the host prints at start-up.
$lines = @(Get-Content $log -ErrorAction SilentlyContinue)
$alive = (adb shell pidof $pkg) -join ""

Write-Output "== probe '$Name' =="
Write-Output ("log lines        : {0}" -f $lines.Count)
Write-Output ("process alive    : {0}" -f $(if ($alive) { "yes (pid $alive)" } else { "NO - died" }))
Write-Output ("nvdrv ioctls     : {0}" -f (($lines | Select-String -Pattern "nvdrv::Ioctl#").Count))
Write-Output ("abort impls      : {0}" -f (($lines | Select-String -Pattern "AbortImpl caller=").Count))
Write-Output ("wild jumps       : {0}" -f (($lines | Select-String -Pattern "wild jump").Count))
Write-Output ("hook restore     : {0}" -f (($lines | Select-String -Pattern "restored to the real").Count))
Write-Output "--- last 12 host lines ---"
$lines | Select-Object -Last 12
Write-Output "--- crash buffer (head) ---"
Get-Content $tomb -ErrorAction SilentlyContinue | Select-Object -First 25
