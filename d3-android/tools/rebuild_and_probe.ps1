# Build one explicit package profile, reuse its preserved signing key, then probe without clearing app data.
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9_-]+$')][string]$Tag,
    [int]$Seconds = 25,
    [ValidateSet('recovery', 'validation', 'genshin', 'genshin-bilibili')][string]$Profile = 'validation',
    [string]$Package,
    [string]$Guest,
    [string]$Keystore,
    [string]$Python = 'python',
    [string]$Sdk = 'D:\workspace\Gdict\android_sdk',
    [string]$Ndk = 'D:\workspace\Gdict\android_sdk\ndk\28.2.13676358',
    [switch]$SkipBuild,
    [switch]$SkipInstall
)

$ErrorActionPreference = 'Stop'
$androidRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repoRoot = (Resolve-Path (Join-Path $androidRoot '..')).Path
$packages = @{
    recovery = 'com.d3mobile.host.recovery'
    validation = 'com.d3mobile.host.validation'
    genshin = 'com.miHoYo.Yuanshen'
    'genshin-bilibili' = 'com.miHoYo.ys.bilibili'
}
if (-not $Package) { $Package = $packages[$Profile] }
if ($Package -ne $packages[$Profile]) { throw '-Package must match -Profile so host, APK and probe use the same private root.' }
if (-not $Guest) { $Guest = Join-Path $repoRoot 'local\android\libd3guest.so' }
if (-not $Keystore) { $Keystore = Join-Path $repoRoot 'local\android\signing\validation-debug.keystore' }
$apkDir = Join-Path $repoRoot "out\android\$Profile\apk"

if (-not $SkipBuild) {
    foreach ($inputFile in @($Guest, $Keystore)) {
        if (-not (Test-Path -LiteralPath $inputFile -PathType Leaf)) { throw "Required preserved input is missing: $inputFile" }
    }
    & $Python -I (Join-Path $PSScriptRoot 'build_android_profile.py') --profile $Profile `
        --guest $Guest --keystore $Keystore --sdk $Sdk --ndk $Ndk
    if ($LASTEXITCODE -ne 0) { throw 'Android profile build failed' }
}

if (-not $SkipInstall) {
    $apkPath = Join-Path $apkDir 'd3host-recovery-debug.apk'
    if (-not (Test-Path -LiteralPath $apkPath -PathType Leaf)) { throw "APK is missing: $apkPath" }
    adb install -r $apkPath
    if ($LASTEXITCODE -ne 0) { throw 'APK upgrade failed; no uninstall or data clear was attempted.' }
}

& pwsh -File (Join-Path $PSScriptRoot 'run_probe.ps1') -Name $Tag -Seconds $Seconds -Package $Package -Keep
if ($LASTEXITCODE -ne 0) { throw 'Device probe failed' }
