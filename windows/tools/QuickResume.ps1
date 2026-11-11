param(
    [ValidateSet('Save','Suspend','Resume','Status')][string]$Action = 'Status',
    [int]$ProcessId = 0,
    [string]$StatePath = (Join-Path $PSScriptRoot '..\..\out\windows\kbm\session\quick-resume.json')
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Add-Type -Namespace QR -Name Native -MemberDefinition @"
[DllImport("ntdll.dll")] public static extern int NtSuspendProcess(System.IntPtr h);
[DllImport("ntdll.dll")] public static extern int NtResumeProcess(System.IntPtr h);
[DllImport("kernel32.dll")] public static extern System.IntPtr OpenProcess(uint access, bool inherit, int pid);
[DllImport("kernel32.dll")] public static extern bool CloseHandle(System.IntPtr h);
"@

$stateDir = Split-Path -Parent $StatePath
$null = New-Item -ItemType Directory -Force -Path $stateDir

function Get-GameProcess {
    param([int]$Id)
    if ($Id -gt 0) { return Get-Process -Id $Id -ErrorAction Stop }
    $items = @(Get-Process -Name '01001B300B9BE000' -ErrorAction Stop)
    if ($items.Count -ne 1) { throw "Expected exactly one game process, found $($items.Count); pass -ProcessId explicitly." }
    return $items[0]
}
function Get-StartTicks([System.Diagnostics.Process]$p) {
    try { return $p.StartTime.ToUniversalTime().ToFileTimeUtc() } catch { return 0 }
}
function Read-State {
    if (-not (Test-Path -LiteralPath $StatePath)) { return $null }
    try { return Get-Content -LiteralPath $StatePath -Raw -Encoding UTF8 | ConvertFrom-Json } catch { return $null }
}
function Write-State($data) {
    $tmp = $StatePath + '.tmp'
    ($data | ConvertTo-Json -Depth 8) + "`n" | Set-Content -LiteralPath $tmp -Encoding UTF8 -NoNewline
    Move-Item -LiteralPath $tmp -Destination $StatePath -Force
}
function Get-LiveSuspended([System.Diagnostics.Process]$p) {
    try { return @($p.Threads | Where-Object { $_.WaitReason -eq 'Suspended' }).Count -gt 0 } catch { return $null }
}
function New-State([System.Diagnostics.Process]$p, [bool]$suspended, [int]$count) {
    return [ordered]@{
        saved_at = [DateTime]::UtcNow.ToString('o')
        pid = $p.Id
        process_start_ticks = (Get-StartTicks $p)
        window_handle = $p.MainWindowHandle.ToInt64()
        window_title = $p.MainWindowTitle
        suspended = $suspended
        suspend_count = $count
        mode = 'process_suspend_resume'
        note = 'Xbox-like Quick Resume: process stays alive; suspend/resume verified without menu or story reload.'
    }
}

$state = Read-State
$p = Get-GameProcess -Id $ProcessId
$liveSuspended = Get-LiveSuspended $p
if ($Action -eq 'Status') {
    $same = $false
    $windowValid = $false
    if ($null -ne $state) {
        $same = ([int]$state.pid -eq $p.Id) -and ([int64]$state.process_start_ticks -eq (Get-StartTicks $p)) -and (($state.PSObject.Properties.Name -contains 'pid') -and ($state.PSObject.Properties.Name -contains 'process_start_ticks'))
        if (($state.PSObject.Properties.Name -contains 'window_handle') -and ($state.PSObject.Properties.Name -contains 'window_title')) {
            $windowValid = ($p.MainWindowHandle.ToInt64() -eq [int64]$state.window_handle) -and ($p.MainWindowTitle -eq $state.window_title)
        }
    }
    [ordered]@{ state=$state; state_present=($null -ne $state); state_corrupt=((Test-Path -LiteralPath $StatePath) -and ($null -eq $state)); same_process_alive=(Get-StartTicks $p) -ne 0; same_process=([bool]$same); live_suspended=$liveSuspended; window_valid=$windowValid; resume_required=($liveSuspended -eq $true); note=$(if ($null -eq $state) { 'NO_QUICK_RESUME_STATE' } else { 'ok' }) } | ConvertTo-Json -Depth 8
    exit 0
}

if ($Action -eq 'Save') {
    if ($liveSuspended -eq $true) { throw 'Refusing Save while the game is suspended; Resume first.' }
    $count = 0
    if ($state -and $state.pid -eq $p.Id -and $state.PSObject.Properties.Name -contains 'suspend_count') { $count = [int]$state.suspend_count }
    Write-State (New-State $p $false $count)
    "saved pid=$($p.Id) hwnd=$($p.MainWindowHandle) to $StatePath"
    exit 0
}

if (-not $state) { throw 'No quick-resume state; run Save first.' }
if ([int]$state.pid -ne $p.Id -or [int64]$state.process_start_ticks -ne (Get-StartTicks $p)) {
    throw 'PID/start-time mismatch; refusing to suspend/resume a different process.'
}
if ($liveSuspended -eq $true -and $Action -eq 'Suspend') {
    throw 'Refusing repeated Suspend: live threads are already suspended.'
}
if ($liveSuspended -eq $true -and $Action -eq 'Resume') {
    $recovery = [QR.Native]::OpenProcess(0x0800, $false, $p.Id)
    if ($recovery -eq [IntPtr]::Zero) { throw 'OpenProcess(PROCESS_SUSPEND_RESUME) failed.' }
    try {
        $status = [QR.Native]::NtResumeProcess($recovery)
        if ($status -ne 0) { throw "NtResumeProcess failed: 0x$($status.ToString('X8'))" }
        $state.suspended = $false
        $state | Add-Member -NotePropertyName resumed_at -NotePropertyValue ([DateTime]::UtcNow.ToString('o')) -Force
        Write-State $state
    } finally { [void][QR.Native]::CloseHandle($recovery) }
    "recovered-and-resumed pid=$($p.Id)"
    exit 0
}

$h = [QR.Native]::OpenProcess(0x0800, $false, $p.Id)
if ($h -eq [IntPtr]::Zero) { throw 'OpenProcess(PROCESS_SUSPEND_RESUME) failed.' }
try {
    if ($Action -eq 'Suspend') {
        $status = [QR.Native]::NtSuspendProcess($h)
        if ($status -ne 0) { throw "NtSuspendProcess failed: 0x$($status.ToString('X8'))" }
        try {
            $state.suspended = $true
            $next = 0
            if ($state.PSObject.Properties.Name -contains 'suspend_count') { $next = [int]$state.suspend_count }
            $state | Add-Member -NotePropertyName suspend_count -NotePropertyValue ($next + 1) -Force
            $state | Add-Member -NotePropertyName suspended_at -NotePropertyValue ([DateTime]::UtcNow.ToString('o')) -Force
            Write-State $state
        } catch {
            [void][QR.Native]::NtResumeProcess($h)
            throw "State write failed; resumed to avoid a stuck process: $($_.Exception.Message)"
        }
        "suspended pid=$($p.Id) count=$($state.suspend_count)"
    } else {
        $status = [QR.Native]::NtResumeProcess($h)
        if ($status -ne 0) { throw "NtResumeProcess failed: 0x$($status.ToString('X8'))" }
        $state.suspended = $false
        $state | Add-Member -NotePropertyName resumed_at -NotePropertyValue ([DateTime]::UtcNow.ToString('o')) -Force
        Write-State $state
        "resumed pid=$($p.Id)"
    }
} finally {
    [void][QR.Native]::CloseHandle($h)
}
