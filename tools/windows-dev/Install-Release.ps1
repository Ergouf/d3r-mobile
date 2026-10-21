param(
    [Parameter(Mandatory = $true)][string]$SourcePath,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedSha256,
    [string]$DestinationDirectory = 'D:\Program Files',
    [string]$ReceiptPath = (Join-Path $PSScriptRoot '..\..\out\windows\packages\install-receipt.json')
)

$ErrorActionPreference = 'Stop'
$releaseSource = (Resolve-Path -LiteralPath $SourcePath).Path
$releaseDirectory = (Resolve-Path -LiteralPath $DestinationDirectory).Path
$releaseTarget = [IO.Path]::GetFullPath((Join-Path $releaseDirectory ([IO.Path]::GetFileName($releaseSource))))
$releaseReceipt = [IO.Path]::GetFullPath($ReceiptPath)
$receiptDirectory = [IO.Path]::GetDirectoryName($releaseReceipt)
$null = New-Item -ItemType Directory -Force -Path $receiptDirectory
$releaseReport = [ordered]@{ success = $false; source = $releaseSource; destination = $releaseTarget }

try {
    if ([IO.Path]::GetExtension($releaseSource) -ine '.zip') { throw 'The source must be a ZIP archive.' }
    if ($releaseSource -ieq $releaseTarget) { throw 'Source and destination must differ.' }
    if (Test-Path -LiteralPath $releaseTarget) { throw 'Destination already exists; refusing to overwrite.' }
    if (Test-Path -LiteralPath ($releaseTarget + '.sha256')) { throw 'Destination checksum already exists; refusing to overwrite.' }
    $sourceHash = (Get-FileHash -LiteralPath $releaseSource -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($sourceHash -ine $ExpectedSha256) { throw 'The source SHA-256 does not match the expected verified archive.' }
    # CreateNew prevents replacement even if another process creates the target after the checks above.
    $sourceStream = $null
    $targetStream = $null
    try {
        $sourceStream = [IO.File]::Open($releaseSource, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        $targetStream = [IO.File]::Open($releaseTarget, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $sourceStream.CopyTo($targetStream)
        $targetStream.Flush($true)
    } finally {
        if ($targetStream) { $targetStream.Dispose() }
        if ($sourceStream) { $sourceStream.Dispose() }
    }
    $targetHash = (Get-FileHash -LiteralPath $releaseTarget -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($targetHash -ine $ExpectedSha256) { throw 'Destination SHA-256 mismatch; source retained.' }
    $checksumStream = $null
    try {
        $checksumStream = [IO.File]::Open($releaseTarget + '.sha256', [IO.FileMode]::CreateNew)
        $checksumBytes = [Text.Encoding]::ASCII.GetBytes($targetHash + '  ' + [IO.Path]::GetFileName($releaseTarget) + [Environment]::NewLine)
        $checksumStream.Write($checksumBytes, 0, $checksumBytes.Length)
    } finally {
        if ($checksumStream) { $checksumStream.Dispose() }
    }
    $releaseReport.success = $true
    $releaseReport.sha256 = $targetHash
    $releaseReport.bytes = (Get-Item -LiteralPath $releaseTarget).Length
    $releaseReport.verified_at = [DateTimeOffset]::Now.ToString('o')
} catch {
    $releaseReport.error = $_.Exception.Message
    throw
} finally {
    $releaseReport | ConvertTo-Json | Set-Content -LiteralPath $releaseReceipt -Encoding utf8
}

# Run from an elevated shell if the chosen destination requires it. This script never requests elevation
# or changes Windows directory permissions, and it retains the verified source archive.
