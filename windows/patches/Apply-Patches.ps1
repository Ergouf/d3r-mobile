param(
    [string]$SourcePath = (Join-Path $PSScriptRoot '..\..\windows\source\ScarletNX-src'),
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$patchSource = (Resolve-Path -LiteralPath $SourcePath).Path
$patchMetadata = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'base.json') -Raw | ConvertFrom-Json
$patchHead = & git -C $patchSource rev-parse HEAD
if ($LASTEXITCODE -ne 0) { throw 'SourcePath must be a ScarletNX Git checkout.' }
if ($patchHead.Trim() -ne $patchMetadata.base_commit) {
    throw "Expected ScarletNX commit $($patchMetadata.base_commit); found $patchHead."
}

# The base patch first, then each extra patch on top of the previous result.
$patchList = @([pscustomobject]@{ patch = $patchMetadata.patch; patch_sha256 = $patchMetadata.patch_sha256 })
if ($patchMetadata.PSObject.Properties.Name -contains 'extra_patches') {
    $patchList += $patchMetadata.extra_patches
}

# A later patch can touch a file an earlier one did, so the earlier one no longer reverses cleanly on its own. When the
# last patch reverses, the whole series is applied.
$lastPatch = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot $patchList[-1].patch)).Path
$lastReverse = & git -C $patchSource apply --reverse --check --ignore-whitespace --whitespace=nowarn $lastPatch 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host ('All Windows source patches are already applied: ' + ($patchList.patch -join ', ') + '.')
    return
}

$applied = @()
foreach ($entry in $patchList) {
    $patchFile = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot $entry.patch)).Path
    $patchHash = (Get-FileHash -LiteralPath $patchFile -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($patchHash -ine $entry.patch_sha256) { throw "Patch checksum differs from base.json: $($entry.patch)" }

    $patchCheck = & git -C $patchSource apply --check --ignore-whitespace --whitespace=nowarn $patchFile 2>&1
    if ($LASTEXITCODE -ne 0) {
        $patchReverse = & git -C $patchSource apply --reverse --check --ignore-whitespace --whitespace=nowarn $patchFile 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "$($entry.patch) is already applied."
            continue
        }
        throw ('Patch cannot be safely applied; source files were not changed: ' + $entry.patch + [Environment]::NewLine +
            ($patchCheck -join [Environment]::NewLine))
    }
    if ($CheckOnly) {
        Write-Host "$($entry.patch): checksum and git apply --check passed."
        continue
    }
    & git -C $patchSource apply --ignore-whitespace --whitespace=nowarn $patchFile
    if ($LASTEXITCODE -ne 0) { throw "git apply failed: $($entry.patch)" }
    $applied += $entry.patch
}
if ($CheckOnly) {
    Write-Host 'All Windows patches passed their checks; source files were not changed.'
    return
}
if ($applied.Count) {
    Write-Host ('Windows source patches applied: ' + ($applied -join ', ') + '. Build with windows/tools/Build.ps1.')
} else {
    Write-Host 'All Windows source patches are already applied.'
}
