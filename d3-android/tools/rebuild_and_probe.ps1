# One-shot bring-up iteration: rebuild the host, package the APK, install it and
# probe the device.
#
#   pwsh -File d3-android/tools/rebuild_and_probe.ps1 -Tag acct2 -Seconds 25
#
# The APK output directory (build/apk-gpu-<Tag>) and the probe name follow -Tag,
# and every APK reuses build/apk-gpu-waitn/local-debug.keystore so upgrades
# install over each other without a signature mismatch.
param(
    [Parameter(Mandatory = $true)][string]$Tag,
    [int]$Seconds = 25,
    [switch]$SkipBuild,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$py = "C:\Users\fengj\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
$guest = "D:\workspace\Diablo\recovery\d3host-20261016-huRwPN\extracted\lib\arm64-v8a\libd3guest.so"
$keystore = Join-Path $root "build\apk-gpu-waitn\local-debug.keystore"
$apkDir = Join-Path $root "build\apk-gpu-$Tag"

if (-not $SkipBuild) {
    Write-Output "== building host =="
    & $py -I (Join-Path $root "tools\build_host.py") --with-gpu `
        --data-root /data/user/0/com.d3mobile.host.recovery/files/runtime `
        --private-root /data/user/0/com.d3mobile.host.recovery `
        --output-dir (Join-Path $root "build\host-gpu") 2>&1 |
        Select-Object -Last 1
    if ($LASTEXITCODE -ne 0) { throw "host build failed" }

    Write-Output "== packaging apk =="
    & $py -I (Join-Path $root "tools\build_apk.py") --host (Join-Path $root "build\host-gpu\libd3host.so") `
        --guest $guest --output-dir $apkDir --keystore $keystore 2>&1 |
        Select-String -Pattern "host sha256|wrote .*apk" | ForEach-Object { $_.Line }
    if ($LASTEXITCODE -ne 0) { throw "apk build failed" }
}

if (-not $SkipInstall) {
    Write-Output "== installing =="
    adb install -r (Join-Path $apkDir "d3host-recovery-debug.apk") 2>&1 | Select-Object -Last 2
}

Write-Output "== probing =="
& pwsh -File (Join-Path $PSScriptRoot "run_probe.ps1") -Name $Tag -Seconds $Seconds
