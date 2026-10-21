param(
    [string]$SourcePath = (Join-Path $PSScriptRoot '..\..\reference\ScarletNX-src'),
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$patchSource = (Resolve-Path -LiteralPath $SourcePath).Path
$patchMetadata = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'base.json') -Raw | ConvertFrom-Json
$patchFile = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot $patchMetadata.patch)).Path
$patchHash = (Get-FileHash -LiteralPath $patchFile -Algorithm SHA256).Hash.ToLowerInvariant()
if ($patchHash -ine $patchMetadata.patch_sha256) { throw 'Patch checksum differs from base.json.' }
$patchHead = & git -C $patchSource rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'SourcePath must be a ScarletNX Git checkout.' }
if ($patchHead.Trim() -ne $patchMetadata.base_commit) {
    throw "Expected ScarletNX commit $($patchMetadata.base_commit); found $patchHead."
}

$patchCheck = & git -C $patchSource apply --check --whitespace=nowarn $patchFile 2>&1
if ($LASTEXITCODE -ne 0) {
    $patchReverse = & git -C $patchSource apply --reverse --check --whitespace=nowarn $patchFile 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host 'The complete Windows FSR patch is already applied.'
        return
    }
    throw ('Patch cannot be safely applied; source files were not changed.' + [Environment]::NewLine + ($patchCheck -join [Environment]::NewLine))
}
if ($CheckOnly) {
    Write-Host 'Patch checksum, base commit and git apply --check passed; source files were not changed.'
    return
}
& git -C $patchSource apply --whitespace=nowarn $patchFile
if ($LASTEXITCODE -ne 0) { throw 'git apply failed.' }
Write-Host 'Windows FSR source patch applied. Build with tools/windows-dev/Build.ps1.'
