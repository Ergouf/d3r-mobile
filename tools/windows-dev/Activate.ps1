param([string]$MsysRoot = 'D:\workspace\msys2\msys64')

$ErrorActionPreference = 'Stop'
$devRoot = (Resolve-Path -LiteralPath $MsysRoot).Path
$devPrefix = Join-Path $devRoot 'clang64'
$devBin = Join-Path $devPrefix 'bin'
foreach ($required in @('clang.exe', 'llvm-config.exe', 'cmake.exe', 'ninja.exe', 'glslangValidator.exe', 'spirv-val.exe', 'VkLayer_khronos_validation.json')) {
    if (-not (Test-Path -LiteralPath (Join-Path $devBin $required))) {
        throw "Missing CLANG64 dependency: $required in $devBin"
    }
}

# Process-local only; this script does not change the registry or machine/user PATH.
$env:MSYSTEM = 'CLANG64'
$env:MSYS2_PATH_TYPE = 'inherit'
$env:VULKAN_SDK = $devPrefix
$env:VK_LAYER_PATH = $devBin
$devPath = @($env:PATH -split ';' | Where-Object { $_ -and $_.TrimEnd('\') -ine $devBin.TrimEnd('\') })
$env:PATH = $devBin + ';' + ($devPath -join ';')
Write-Host "CLANG64 development environment: $devPrefix"
Write-Host 'Vulkan development components: MSYS2 packages; GPU runtime: installed Intel driver.'
