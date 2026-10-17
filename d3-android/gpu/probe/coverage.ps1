<#
  M0 coverage probe: syntax-check every Eden translation unit that the GPU port
  needs (video_core, optionally shader_recompiler) against our shim layer.

  Usage:
    pwsh -File coverage.ps1                 # Vulkan-side video_core, out-of-scope trees skipped
    pwsh -File coverage.ps1 -All            # include OpenGL / NVDEC / post-processing too
    pwsh -File coverage.ps1 -Tree shader_recompiler

  Output: gpu/probe/coverage-<tree>.json + console summary by error signature.
#>
param(
    [string]$Tree = 'video_core',
    [int]$Throttle = 10,
    [switch]$FirstError,
    [switch]$All,
    [string[]]$Files
)

$ErrorActionPreference = 'Stop'

$Root    = 'D:\workspace\Diablo'
$Shim    = Join-Path $Root 'd3-android\gpu\shim'
$Third   = Join-Path $Root 'd3-android\gpu\third_party'
$Eden    = Join-Path $Root 'reference\eden'
$EdenSrc = Join-Path $Eden 'src'
$Clang   = 'D:\workspace\Gdict\android_sdk\ndk\28.2.13676358\toolchains\llvm\prebuilt\windows-x86_64\bin\clang++.exe'

# Trees that cannot contribute to the first Vulkan frame.
$exclude = @(
    '\\renderer_opengl\\',
    '\\host1x\\codecs\\',
    '\\host1x\\ffmpeg\.cpp$',
    '\\host1x\\vic\.cpp$',
    '\\post_processing\\',
    '\\present\\post_process\.cpp$'
)
if ($All) { $exclude = @() }

$common = @(
    '--target=aarch64-linux-android34', '-std=c++20', '-fsyntax-only',
    '-D_LIBCPP_ENABLE_EXPERIMENTAL=1',
    '-I', $Shim,
    '-I', (Join-Path $Third 'Vulkan-Headers\include'),
    '-I', (Join-Path $Third 'Vulkan-Utility-Libraries\include'),
    '-I', (Join-Path $Third 'VMA\include'),
    '-I', (Join-Path $Root 'd3-android\gpu\gen\include'),
    '-I', (Join-Path $Third 'fmt\include'),
    '-I', (Join-Path $Third 'boost\boost_1_86_0'),
    '-I', (Join-Path $Eden 'externals\stb'),
    '-I', (Join-Path $Eden 'externals\bc_decoder'),
    '-I', $EdenSrc,
    '-Wno-ignored-attributes', '-Wno-unused-command-line-argument'
)

if (-not $Files) {
    $Files = Get-ChildItem -Path (Join-Path $EdenSrc $Tree) -Recurse -Filter *.cpp -File |
             Where-Object { $p = $_.FullName; -not ($exclude | Where-Object { $p -match $_ }) } |
             ForEach-Object { $_.FullName }
}

Write-Host "probe: $($Files.Count) files under $Tree (excluded trees: $(if ($All) { 'none' } else { $exclude.Count }))"

$results = $Files | ForEach-Object -Parallel {
    $cc = $using:Clang
    $args_ = $using:common
    $out = @(& $cc @args_ $_ 2>&1 | ForEach-Object { "$_" })
    $code = $LASTEXITCODE
    $text = ($out -join "`n")
    $err = ($out | Where-Object { $_ -match 'error:' } | Select-Object -First 1) -as [string]
    [pscustomobject]@{
        File    = $_
        Rel     = $_.Substring($using:EdenSrc.Length + 1)
        Ok      = ($code -eq 0)
        Errors  = ($out | Select-String -Pattern 'error:' -AllMatches).Count
        First   = ($err -replace '^\s+', '')
        Text    = if ($using:FirstError) { $null } else { $text }
    }
} -ThrottleLimit $Throttle

$ok      = @($results | Where-Object Ok)
$bad     = @($results | Where-Object { -not $_.Ok })
$outPath = Join-Path $Root "d3-android\gpu\probe\coverage-$Tree.json"
$results | ConvertTo-Json -Depth 4 | Set-Content -Path $outPath -Encoding UTF8

Write-Host ""
Write-Host ("PASS {0}/{1}  FAIL {2}" -f $ok.Count, $results.Count, $bad.Count)
Write-Host ""
Write-Host "== error signatures (top) =="
$bad | ForEach-Object {
    if ($_.First -match "fatal error: '([^']+)' file not found") { "missing header: $($Matches[1])" }
    elseif ($_.First -match "no member named '([^']+)' in '([^']+)'") { "no member: $($Matches[2])::$($Matches[1])" }
    elseif ($_.First -match "no type named '([^']+)' in namespace '([^']+)'") { "no type: $($Matches[2])::$($Matches[1])" }
    elseif ($_.First -match "no member named '([^']+)' in namespace '([^']+)'") { "no member: $($Matches[2])::$($Matches[1])" }
    elseif ($_.First -match "use of undeclared identifier '([^']+)'") { "undeclared: $($Matches[1])" }
    elseif ($_.First -match "unknown type name '([^']+)'") { "unknown type: $($Matches[1])" }
    else { $_.First }
} | Group-Object | Sort-Object Count -Descending | Select-Object Count, Name | Format-Table -AutoSize -Wrap

Write-Host "json: $outPath"
