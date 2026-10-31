param(
    [Parameter(Mandatory = $true)][string]$Elf,
    [Parameter(Mandatory = $true)][string]$GhidraHome,
    [Parameter(Mandatory = $true)][string]$JavaHome,
    [string]$ProjectDir = (Join-Path $PSScriptRoot '..\..\out\windows\kbm\ghidra'),
    [string]$ProjectName = 'D3Main',
    [string]$AnalysisTimeout = '900'
)

$ErrorActionPreference = 'Stop'
$Elf = (Resolve-Path -LiteralPath $Elf).Path
$GhidraHome = (Resolve-Path -LiteralPath $GhidraHome).Path
$JavaHome = (Resolve-Path -LiteralPath $JavaHome).Path
$headless = Join-Path $GhidraHome 'support\analyzeHeadless.bat'
if (!(Test-Path -LiteralPath $headless)) {
    throw "analyzeHeadless.bat not found under $GhidraHome"
}
New-Item -ItemType Directory -Force -Path $ProjectDir | Out-Null

$env:JAVA_HOME = $JavaHome
$env:GHIDRA_INSTALL_DIR = $GhidraHome
$env:GHIDRA_HEADLESS_MAXMEM = '8G'
$scriptPath = Join-Path $PSScriptRoot 'ghidra_scripts'

& $headless $ProjectDir $ProjectName `
    -import $Elf `
    -overwrite `
    -analysisTimeoutPerFile $AnalysisTimeout `
    -scriptPath $scriptPath `
    -postScript FindUiRefs.java
if ($LASTEXITCODE -ne 0) { throw "Ghidra analysis failed (exit $LASTEXITCODE)" }
