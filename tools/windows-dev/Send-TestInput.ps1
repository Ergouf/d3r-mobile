<#
.SYNOPSIS
Sends one guest-controller pulse through ScarletNX's own INI test-script reader.
.EXAMPLE
.\tools\windows-dev\Send-TestInput.ps1 -Buttons 1 -DurationMs 500
.NOTES
No keyboard, Win32 input, window or save APIs are used. Hex masks are Switch buttons:
1=A, 2=B, 400=Plus, 1000=Left, 2000=Up, 4000=Right, 8000=Down.
The runtime's overlay must be closed. Start the game without --script/--press_len.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^(?:0[xX])?[0-9a-fA-F]{1,16}$')]
    [string]$Buttons,
    [ValidateRange(1, 10000)]
    [int]$DurationMs = 500,
    [string]$GameRoot = 'D:\Games\DiabloIII',
    [ValidateRange(3, 60)]
    [int]$ReloadTimeoutSeconds = 15
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$testEncoding = [Text.UTF8Encoding]::new($false, $true)
$testToken = [Guid]::NewGuid().ToString('N')
$testScriptValue = '0f:' + ([Convert]::ToUInt64(($Buttons -replace '^0[xX]', ''), 16)).ToString('x')
$testMarkerStart = '; BEGIN Codex temporary test input ' + $testToken
$testMarkerEnd = '; END Codex temporary test input ' + $testToken
$testSection = '[Codex temporary test input ' + $testToken + ']'

function Get-ByteHash([byte[]]$Bytes) {
    $hashAlgorithm = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($hashAlgorithm.ComputeHash($Bytes)).Replace('-', '') }
    finally { $hashAlgorithm.Dispose() }
}

function Get-SettingsValues([string]$Text) {
    # ScarletNX ignores section names here, uses exact key spelling, and keeps the last duplicate.
    $values = [Collections.Generic.Dictionary[string, string]]::new([StringComparer]::Ordinal)
    foreach ($line in ($Text.TrimStart([char]0xFEFF) -split "`n")) {
        $trimmed = $line.Trim([char[]]" `t`r")
        if (!$trimmed -or $trimmed.StartsWith(';') -or $trimmed.StartsWith('#') -or $trimmed.StartsWith('[')) { continue }
        $equals = $trimmed.IndexOf('=')
        if ($equals -lt 0) { continue }
        $key = $trimmed.Substring(0, $equals).Trim([char[]]" `t")
        $values[$key] = $trimmed.Substring($equals + 1).Trim([char[]]" `t`r")
    }
    return ,$values
}

function Read-IniSnapshot {
    $readTimer = [Diagnostics.Stopwatch]::StartNew()
    while ($true) {
        try {
            $bytes = [IO.File]::ReadAllBytes($testIniPath)
            $textValue = $testEncoding.GetString($bytes)
            return [pscustomobject]@{
                Bytes = $bytes; Text = $textValue; Hash = (Get-ByteHash $bytes)
                Values = (Get-SettingsValues $textValue)
            }
        } catch [IO.IOException] {
            if ($readTimer.Elapsed.TotalSeconds -ge 3) { throw }
            Start-Sleep -Milliseconds 100
        }
    }
}

function Test-GameAlive {
    try {
        $liveGame = Get-Process -Id $testGameProcessId -ErrorAction Stop
        return !$liveGame.HasExited -and $liveGame.StartTime.ToUniversalTime().Ticks -eq $testGameStartTicks
    } catch { return $false }
}

function Write-IniCompared([object]$Expected, [byte[]]$Replacement, [switch]$MarkTouched, [object]$Cursor = $null) {
    # A short exclusive lock makes compare + write indivisible with respect to the runtime's read/replace.
    # A poll that meets the lock simply cannot read this file and retries on its next normal poll.
    $writeTimer = [Diagnostics.Stopwatch]::StartNew()
    while ($true) {
        $iniStream = $null
        try {
            $iniStream = [IO.File]::Open($testIniPath, [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
            $currentBytes = [byte[]]::new([int]$iniStream.Length)
            $readCount = 0
            while ($readCount -lt $currentBytes.Length) {
                $received = $iniStream.Read($currentBytes, $readCount, $currentBytes.Length - $readCount)
                if (!$received) { throw [IO.EndOfStreamException]::new('INI ended during the compare.') }
                $readCount += $received
            }
            if ((Get-ByteHash $currentBytes) -cne $Expected.Hash) { return $false }
            if ($null -ne $Cursor) {
                # Reset the observer only after the INI lock/compare succeeded, immediately before writing.
                $freshCursor = New-LogCursor
                $Cursor.Offset = $freshCursor.Offset
                $Cursor.Tail = ''
            }
            if ($MarkTouched) { $testState.Touched = $true }
            $iniStream.Position = 0
            $iniStream.Write($Replacement, 0, $Replacement.Length)
            $iniStream.SetLength($Replacement.Length)
            $iniStream.Flush($true)
            return $true
        } catch [IO.IOException] {
            if ($writeTimer.Elapsed.TotalSeconds -ge 3) { throw }
            Start-Sleep -Milliseconds 100
        } finally {
            if ($null -ne $iniStream) { $iniStream.Dispose() }
        }
    }
}

function New-LogCursor {
    $logLength = if ([IO.File]::Exists($testLogPath)) { ([IO.FileInfo]::new($testLogPath)).Length } else { 0L }
    return [pscustomobject]@{ Offset = [long]$logLength; Tail = '' }
}

function Wait-IniReload([object]$Cursor) {
    $reloadTimer = [Diagnostics.Stopwatch]::StartNew()
    $reloadPattern = '(?im)^\[[^\r\n]*\]\s+settings:\s+' + [regex]::Escape($testIniPath) + '\s+reloaded\s*$'
    while ($reloadTimer.Elapsed.TotalSeconds -lt $ReloadTimeoutSeconds) {
        if (!(Test-GameAlive)) { throw 'The selected game process exited before INI reload was confirmed.' }
        $logStream = $null
        try {
            $logStream = [IO.File]::Open($testLogPath, [IO.FileMode]::Open, [IO.FileAccess]::Read,
                ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
            if ($logStream.Length -lt $Cursor.Offset) { throw [InvalidOperationException]::new('Game log was truncated; reload cannot be confirmed.') }
            $remaining = $logStream.Length - $Cursor.Offset
            if ($remaining -gt 0) {
                if ($remaining -gt 16MB) { throw [InvalidOperationException]::new('Unexpectedly large new log data; reload cannot be confirmed.') }
                $null = $logStream.Seek($Cursor.Offset, [IO.SeekOrigin]::Begin)
                $newBytes = [byte[]]::new([int]$remaining)
                $received = $logStream.Read($newBytes, 0, $newBytes.Length)
                $Cursor.Offset += $received
                $Cursor.Tail += [Text.Encoding]::UTF8.GetString($newBytes, 0, $received)
                if ($Cursor.Tail -match $reloadPattern) {
                    # The runtime logs before rewriting its normalized INI. Give that short write time to finish.
                    Start-Sleep -Milliseconds 150
                    return
                }
                if ($Cursor.Tail.Length -gt 65536) { $Cursor.Tail = $Cursor.Tail.Substring($Cursor.Tail.Length - 32768) }
            }
        } catch [IO.IOException] {
            # Sharing/replace races on the log are transient; the process identity and timeout still apply.
        } finally {
            if ($null -ne $logStream) { $logStream.Dispose() }
        }
        Start-Sleep -Milliseconds 100
    }
    throw "Timed out after $ReloadTimeoutSeconds seconds waiting for a new INI reload log line."
}

function Test-OtherValuesUnchanged([object]$Current) {
    foreach ($key in $testOriginal.Values.Keys) {
        if ($key -ceq 'script' -or $key -ceq 'press_len') { continue }
        if (!$Current.Values.ContainsKey($key) -or $Current.Values[$key] -cne $testOriginal.Values[$key]) { return $false }
    }
    foreach ($key in $Current.Values.Keys) {
        if ($key -ceq 'script' -or $key -ceq 'press_len') { continue }
        if (!$testOriginal.Values.ContainsKey($key)) { return $false }
    }
    return $true
}

function Test-AllValuesOriginal([object]$Current) {
    if ($Current.Values.Count -ne $testOriginal.Values.Count) { return $false }
    foreach ($key in $testOriginal.Values.Keys) {
        if (!$Current.Values.ContainsKey($key) -or $Current.Values[$key] -cne $testOriginal.Values[$key]) { return $false }
    }
    return $true
}

function Remove-TestLines([string]$Text, [string[]]$Keys) {
    $insideOwnSection = $false
    $keptLines = foreach ($line in ($Text -split "`n")) {
        $trimmed = $line.Trim([char[]]" `t`r")
        if ($trimmed -ceq $testMarkerStart) { $insideOwnSection = $true; continue }
        if ($trimmed -ceq $testMarkerEnd) { $insideOwnSection = $false; continue }
        if ($trimmed -ceq $testSection) { continue }
        # If another writer added a later duplicate, retain their row and remove our now-shadowed rows.
        # Unknown settings inserted inside this section also survive cleanup.
        if ($insideOwnSection) {
            if ($trimmed -cmatch '^script[ \t]*=[ \t]*(.*)$' -and
                ($Matches[1] -ceq $testScriptValue -or $Matches[1] -ceq $testState.Script)) { continue }
            if ($trimmed -cmatch '^press_len[ \t]*=[ \t]*(.*)$' -and
                ($Matches[1] -ceq $DurationMs.ToString() -or $Matches[1] -ceq '300')) { continue }
        }
        $remove = $false
        foreach ($key in $Keys) {
            if ($line -cmatch ('^[ \t]*' + [regex]::Escape($key) + '[ \t]*=')) { $remove = $true; break }
        }
        if (!$remove) { $line }
    }
    return ($keptLines -join "`n")
}

function Add-TestSection([string]$Text, [string[]]$Rows) {
    $eol = if ($Text.Contains("`r`n")) { "`r`n" } else { "`n" }
    return $Text + $eol + $testMarkerStart + $eol + $testSection + $eol + ($Rows -join $eol) + $eol + $testMarkerEnd + $eol
}

function Clear-TestState {
    for ($attempt = 0; $attempt -lt 8; $attempt++) {
        $snapshot = Read-IniSnapshot
        # A missing test key still needs an explicit reset: deleting it does not reset runtime memory.
        $ownScript = $testState.OwnScript -and (!$snapshot.Values.ContainsKey('script') -or $snapshot.Values['script'] -ceq $testState.Script)
        $ownLength = $testState.OwnLength -and (!$snapshot.Values.ContainsKey('press_len') -or $snapshot.Values['press_len'] -ceq $testState.Length)
        if (!(Test-OtherValuesUnchanged $snapshot)) { $testState.Concurrent = $true }
        if (!$ownScript) { $testState.OwnScript = $false; $testState.Concurrent = $true }
        if (!$ownLength) { $testState.OwnLength = $false; $testState.Concurrent = $true }
        if (!$ownScript -and !$ownLength) { return }
        $keys = @(); $rows = @()
        if ($ownScript) { $keys += 'script'; $rows += 'script=' }
        if ($ownLength) { $keys += 'press_len'; $rows += 'press_len=300' }
        $clearText = Add-TestSection (Remove-TestLines $snapshot.Text $keys) $rows
        $cursor = New-LogCursor
        if (!(Write-IniCompared $snapshot ($testEncoding.GetBytes($clearText)) -Cursor $cursor)) { continue }
        if ($ownScript) { $testState.Script = '' }
        if ($ownLength) { $testState.Length = '300' }
        if (Test-GameAlive) { Wait-IniReload $cursor }
        $testState.ClearConfirmed = $true
        return
    }
    throw 'INI kept changing concurrently while clearing this test input.'
}

function Restore-TestIni {
    if ((Test-GameAlive) -and !$testState.ClearConfirmed -and $testState.OwnScript) {
        throw 'The explicit script reset was not confirmed; leaving the reset on disk and retaining the backup for recovery.'
    }
    for ($attempt = 0; $attempt -lt 8; $attempt++) {
        $snapshot = Read-IniSnapshot
        $ownScript = $testState.OwnScript -and $snapshot.Values.ContainsKey('script') -and $snapshot.Values['script'] -ceq $testState.Script
        $ownLength = $testState.OwnLength -and $snapshot.Values.ContainsKey('press_len') -and $snapshot.Values['press_len'] -ceq $testState.Length
        if (!(Test-OtherValuesUnchanged $snapshot) -or !$ownScript -or !$ownLength) { $testState.Concurrent = $true }
        if (!$testState.Concurrent) {
            $replacement = $testOriginal.Bytes
        } else {
            $keys = @(); $rows = @()
            if ($ownScript) {
                $keys += 'script'
                if ($testOriginal.Values.ContainsKey('script')) { $rows += 'script=' + $testOriginal.Values['script'] }
            }
            if ($ownLength) {
                $keys += 'press_len'
                if ($testOriginal.Values.ContainsKey('press_len')) { $rows += 'press_len=' + $testOriginal.Values['press_len'] }
            }
            $restoreText = Remove-TestLines $snapshot.Text $keys
            if ($rows.Count) { $restoreText += "`r`n[Other]`r`n" + ($rows -join "`r`n") + "`r`n" }
            $replacement = $testEncoding.GetBytes($restoreText)
        }
        $cursor = New-LogCursor
        if (!(Write-IniCompared $snapshot $replacement -Cursor $cursor)) { continue }
        # Observe the restore as well: an absent extra key does not reset its in-memory value.
        if (Test-GameAlive) { Wait-IniReload $cursor }
        if (!$testState.Concurrent) {
            # A reload rewrites the INI's formatting. Reapply the byte-for-byte backup after that rewrite.
            # This final byte-only restore has identical effective values and needs no additional reload.
            $formatted = Read-IniSnapshot
            if ((Test-AllValuesOriginal $formatted) -and
                (Write-IniCompared $formatted $testOriginal.Bytes)) {
                $testState.RestoredOriginal = $true
            } else {
                $testState.Concurrent = $true
            }
        }
        return
    }
    throw 'INI kept changing concurrently while restoring this test configuration.'
}

$resolvedRoot = (Resolve-Path -LiteralPath $GameRoot).ProviderPath.TrimEnd([char[]]'\/')
$rootPrefix = $resolvedRoot + [IO.Path]::DirectorySeparatorChar
$targets = @(Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^[0-9a-fA-F]{16}\.exe$' -and $_.ExecutablePath -and
    ([IO.Path]::GetFullPath($_.ExecutablePath)).StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)
})
if ($targets.Count -ne 1) { throw "Expected exactly one running title EXE under $resolvedRoot; found $($targets.Count)." }
if (!$targets[0].CommandLine) { throw 'Cannot inspect the game command line; refusing to change its INI.' }
if ($targets[0].CommandLine -match '(?i)(?:^|[\s"])--(?:script|press_len)(?=[=\s"]|$)') {
    throw 'Restart the game without CLI --script and --press_len before using this helper.'
}
$testGameProcessId = [int]$targets[0].ProcessId
$testGameStartTicks = (Get-Process -Id $testGameProcessId).StartTime.ToUniversalTime().Ticks
$testIniPath = [IO.Path]::ChangeExtension([IO.Path]::GetFullPath($targets[0].ExecutablePath), '.ini')
$testLogPath = [IO.Path]::ChangeExtension($testIniPath, '.log')
$testOriginal = Read-IniSnapshot
if ($testOriginal.Values.ContainsKey('script') -and $testOriginal.Values['script']) {
    throw 'The INI already contains a nonempty test script; refusing to replace or replay it.'
}
if ($testOriginal.Text -match '(?m)^; BEGIN Codex temporary test input ') {
    throw 'An earlier temporary input section is present; inspect and clean that run first.'
}
$backupDirectory = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\out\windows\diagnostics\frame-pacing\input-backup'))
$null = [IO.Directory]::CreateDirectory($backupDirectory)
$backupPath = Join-Path $backupDirectory ([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + "-pid$testGameProcessId-$testToken.ini")
$backupStream = [IO.File]::Open($backupPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
try { $backupStream.Write($testOriginal.Bytes, 0, $testOriginal.Bytes.Length); $backupStream.Flush($true) }
finally { $backupStream.Dispose() }

$testState = [pscustomobject]@{
    Touched = $false; OwnScript = $true; OwnLength = $true; Script = $testScriptValue
    Length = $DurationMs.ToString([Globalization.CultureInfo]::InvariantCulture)
    Concurrent = $false; ClearConfirmed = $false; RestoredOriginal = $false
}
$testFailure = $null
$cleanupErrors = [Collections.Generic.List[string]]::new()
try {
    if (!(Test-GameAlive)) { throw 'The selected game process has exited.' }
    $pulseRows = @(('press_len=' + $testState.Length), ('script=' + $testScriptValue))
    $pulseText = Add-TestSection $testOriginal.Text $pulseRows
    $cursor = New-LogCursor
    if (!(Write-IniCompared $testOriginal ($testEncoding.GetBytes($pulseText)) -MarkTouched -Cursor $cursor)) {
        throw 'INI changed before the pulse was written; the backup is retained and no test input was installed.'
    }
    Wait-IniReload $cursor
    Start-Sleep -Milliseconds ($DurationMs + 150)
} catch {
    $testFailure = $_
} finally {
    if ($testState.Touched) {
        try { Clear-TestState } catch { $cleanupErrors.Add('Clear: ' + $_.Exception.Message) }
        try { Restore-TestIni } catch { $cleanupErrors.Add('Restore: ' + $_.Exception.Message) }
    }
}

if ($cleanupErrors.Count) {
    throw ("Test input cleanup was not fully confirmed. Backup: $backupPath. " + ($cleanupErrors -join ' | ') +
        $(if ($null -ne $testFailure) { ' | Original error: ' + $testFailure.Exception.Message } else { '' }))
}
if ($null -ne $testFailure) { throw $testFailure }
[pscustomobject]@{
    ProcessId = $testGameProcessId; Buttons = $testScriptValue.Substring(3); DurationMs = $DurationMs
    Backup = $backupPath; ClearConfirmed = $testState.ClearConfirmed
    OriginalBytesRestored = $testState.RestoredOriginal; ConcurrentSettingsPreserved = $testState.Concurrent
}
