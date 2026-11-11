param(
    [string]$MsysRoot = 'D:\workspace\msys2\msys64',
    [string]$OutputPath = (Join-Path $PSScriptRoot '..\..\out\windows\dependencies')
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Activate.ps1') -MsysRoot $MsysRoot
$null = New-Item -ItemType Directory -Path $OutputPath -Force
$devOutput = (Resolve-Path -LiteralPath $OutputPath).Path
$devBin = Join-Path $MsysRoot 'clang64\bin'
$devExe = Join-Path $devOutput 'vulkan-smoke.exe'
$devSpv = Join-Path $devOutput 'smoke.spv'
$devBuildLog = Join-Path $devOutput 'compile.log'
$devRunLog = Join-Path $devOutput 'runtime.json'
$devErrorLog = Join-Path $devOutput 'validation.log'

& (Join-Path $devBin 'clang.exe') '-std=c11' '-Wall' '-Wextra' '-Werror' (Join-Path $PSScriptRoot 'vulkan-smoke.c') '-o' $devExe '-lvulkan-1' 2>&1 | Set-Content -LiteralPath $devBuildLog -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw "C compile/link failed. See $devBuildLog" }
& (Join-Path $devBin 'glslangValidator.exe') '-V' '--target-env' 'vulkan1.3' (Join-Path $PSScriptRoot 'smoke.comp') '-o' $devSpv 2>&1 | Add-Content -LiteralPath $devBuildLog -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw "GLSL compilation failed. See $devBuildLog" }
& (Join-Path $devBin 'spirv-val.exe') '--target-env' 'vulkan1.3' $devSpv 2>&1 | Add-Content -LiteralPath $devBuildLog -Encoding utf8
if ($LASTEXITCODE -ne 0) { throw "SPIR-V validation failed. See $devBuildLog" }

$devProcess = Start-Process -FilePath $devExe -ArgumentList ('"' + $devSpv + '"') -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $devRunLog -RedirectStandardError $devErrorLog
if ($devProcess.ExitCode -ne 0) { throw "Vulkan runtime check failed. See $devErrorLog" }
$devRuntime = Get-Content -LiteralPath $devRunLog -Raw | ConvertFrom-Json
$devVersions = [ordered]@{}
foreach ($devTool in @('clang', 'llvm-config', 'ld.lld', 'cmake', 'ninja', 'glslangValidator', 'spirv-val')) {
    $devVersion = & (Join-Path $devBin ($devTool + '.exe')) '--version' 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Version query failed: $devTool" }
    $devVersions[$devTool] = [string]($devVersion | Select-Object -First 1)
}
$devPackages = @(
    'mingw-w64-clang-x86_64-clang', 'mingw-w64-clang-x86_64-llvm', 'mingw-w64-clang-x86_64-lld',
    'mingw-w64-clang-x86_64-cmake', 'mingw-w64-clang-x86_64-ninja', 'mingw-w64-clang-x86_64-nasm',
    'mingw-w64-clang-x86_64-python', 'mingw-w64-clang-x86_64-pkgconf',
    'mingw-w64-clang-x86_64-vulkan-headers', 'mingw-w64-clang-x86_64-vulkan-loader',
    'mingw-w64-clang-x86_64-vulkan-utility-libraries', 'mingw-w64-clang-x86_64-vulkan-validation-layers',
    'mingw-w64-clang-x86_64-spirv-headers', 'mingw-w64-clang-x86_64-glslang',
    'mingw-w64-clang-x86_64-spirv-tools', 'mingw-w64-clang-x86_64-vk-bootstrap',
    'git', 'make', 'patch', 'perl', 'patchutils'
)
$devInventory = & (Join-Path $MsysRoot 'usr\bin\pacman.exe') '-Q' @devPackages 2>&1
if ($LASTEXITCODE -ne 0) { throw 'Required development package inventory failed.' }
$devInventory | Set-Content -LiteralPath (Join-Path $devOutput 'packages.txt') -Encoding utf8
$devDrivers = @(Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match '^Intel' } | Select-Object Name, DriverVersion)
$devReport = [ordered]@{
    date = [DateTimeOffset]::Now.ToString('o')
    msys_root = (Resolve-Path -LiteralPath $MsysRoot).Path
    development_distribution = 'MSYS2 CLANG64 Vulkan development packages (not the LunarG SDK installer)'
    tools = $devVersions
    c_compile_and_link = 'passed'
    glsl_compile_vulkan_1_3 = 'passed'
    spirv_validate_vulkan_1_3 = 'passed'
    vulkan_runtime = $devRuntime
    windows_gpu_driver = $devDrivers
    shader_execution_tested = $false
    note = 'Creates the device and shader module; does not dispatch the shader or benchmark a game.'
}
$devReport | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $devOutput 'dependency-validation.json') -Encoding utf8
$devReport | ConvertTo-Json -Depth 8
