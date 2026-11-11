param(
    [string]$MsysRoot = 'D:\workspace\msys2\msys64',
    [string]$SourcePath = (Join-Path $PSScriptRoot '..\..\windows\source\ScarletNX-src'),
    [string]$BuildPath = (Join-Path $PSScriptRoot '..\..\out\windows\build'),
    [switch]$Configure
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Activate.ps1') -MsysRoot $MsysRoot
$devSource = (Resolve-Path -LiteralPath $SourcePath).Path
$devBuildScript = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'build.sh')).Path
$devBuildPath = [IO.Path]::GetFullPath($BuildPath)
$devConfigure = if ($Configure) { 'configure' } else { 'build' }

# Login shell selects /clang64/bin before /usr/bin; do not load ScarletNX's llvm-mingw env.ps1.
& (Join-Path $MsysRoot 'usr\bin\bash.exe') -lc 'exec bash "$1" "$2" "$3" "$4"' 'windows-dev-build' $devBuildScript $devSource $devConfigure $devBuildPath
if ($LASTEXITCODE -ne 0) { throw "ScarletNX build failed (exit $LASTEXITCODE)." }
