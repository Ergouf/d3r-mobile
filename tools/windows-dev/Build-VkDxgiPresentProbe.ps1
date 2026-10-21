param([string]$MsysRoot = 'D:\workspace\msys2\msys64')

$ErrorActionPreference = 'Stop'
$vkProbeRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
. (Join-Path $PSScriptRoot 'Activate.ps1') -MsysRoot $MsysRoot
$vkProbeUpstream = Join-Path $vkProbeRoot 'local\tools\vk-dxgi\vk_dxgi.h'
$vkProbeExpectedHash = '7F7AD8426561BAA6BFF62C64B008CF008AB84D04FFA1FF0FFFD4EBB3A4095148'
if ((Get-FileHash -LiteralPath $vkProbeUpstream -Algorithm SHA256).Hash -ne $vkProbeExpectedHash) {
    throw 'vk_dxgi upstream header differs from pinned commit27950d85af4ad67a5042b2fcda7f04562e671302'
}
$vkProbeCompat = Join-Path $vkProbeRoot 'out\windows\vk-dxgi-compat'
New-Item -ItemType Directory -Path $vkProbeCompat -Force | Out-Null
$vkProbeHeader = [IO.File]::ReadAllText($vkProbeUpstream)
# Upstream forward-declares this enum with fixed int, but MinGW defines it without a fixed underlying type.
# Include MinGW's actual declaration in the generated copy; resource/synchronization implementation stays intact.
$vkProbeForward = 'enum D3D_FEATURE_LEVEL : int;'
if (-not $vkProbeHeader.Contains($vkProbeForward)) { throw 'Expected enum declaration missing' }
$vkProbeHeader = $vkProbeHeader.Replace($vkProbeForward, '#include <d3dcommon.h>')
[IO.File]::WriteAllText((Join-Path $vkProbeCompat 'vk_dxgi.h'), $vkProbeHeader, [Text.UTF8Encoding]::new($false))
Copy-Item -LiteralPath (Join-Path $vkProbeRoot 'local\tools\vk-dxgi\LICENSE') -Destination (Join-Path $vkProbeCompat 'LICENSE')
$vkProbeSource = Join-Path $vkProbeRoot 'tools\windows-dev\vk-dxgi-present-probe.cpp'
$vkProbeExecutable = Join-Path $vkProbeRoot 'out\windows\vk-dxgi-present-probe.exe'
& clang++ -std=c++20 -O2 -Wall -Wextra -Werror -isystem $vkProbeCompat $vkProbeSource -o $vkProbeExecutable -lvulkan-1 -ld3d12 -ldxgi -ldxguid -luser32
if ($LASTEXITCODE -ne 0) { throw "vk-dxgi probe compile failed: $LASTEXITCODE" }
Write-Output $vkProbeExecutable
