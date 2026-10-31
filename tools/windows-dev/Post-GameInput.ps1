<#
.SYNOPSIS
Posts keyboard / mouse messages straight to the game window (no focus needed).
.DESCRIPTION
Uses PostMessage with scan codes, which the ScarletNX SDL backend turns into
the same events a focused window would get. This never touches whatever window
is in the foreground, so it is safe while another app is being used.
.EXAMPLE
.\Post-GameInput.ps1 -Key space
.\Post-GameInput.ps1 -Key down -Repeat 3
.\Post-GameInput.ps1 -Click 1536,960
.\Post-GameInput.ps1 -Move 1536,960
#>
[CmdletBinding(DefaultParameterSetName = 'Key')]
param(
    [Parameter(ParameterSetName = 'Key', Mandatory = $true)]
    [string]$Key,
    [Parameter(ParameterSetName = 'Key')]
    [ValidateRange(1, 50)]
    [int]$Repeat = 1,
    [Parameter(ParameterSetName = 'Key')]
    [ValidateRange(10, 5000)]
    [int]$HoldMs = 80,
    [Parameter(ParameterSetName = 'Click', Mandatory = $true)]
    [string]$Click,
    [Parameter(ParameterSetName = 'Move', Mandatory = $true)]
    [string]$Move,
    [ValidateSet('left', 'right')]
    [string]$Button = 'left',
    [int]$ProcessId = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Add-Type -Namespace GamePost -Name Native -MemberDefinition @"
[DllImport("user32.dll", SetLastError = true)] public static extern bool PostMessage(System.IntPtr h, uint msg, System.IntPtr w, System.IntPtr l);
[DllImport("user32.dll")] public static extern uint MapVirtualKey(uint code, uint mapType);
"@

if ($ProcessId -eq 0) {
    $candidates = @(Get-CimInstance Win32_Process | Where-Object {
        $_.Name -match '^[0-9a-fA-F]{16}\.exe$' -and $_.ExecutablePath -like 'D:\Games\DiabloIII\*'
    })
    if ($candidates.Count -ne 1) { throw "Expected one running game; found $($candidates.Count). Pass -ProcessId." }
    $ProcessId = [int]$candidates[0].ProcessId
}
$proc = Get-Process -Id $ProcessId -ErrorAction Stop
$hwnd = $proc.MainWindowHandle
if ($hwnd -eq [IntPtr]::Zero) { throw "Process $ProcessId has no main window." }

$scanCodes = @{
    'space' = 0x39; 'enter' = 0x1C; 'esc' = 0x01; 'tab' = 0x0F; 'backspace' = 0x0E
    'up' = 0x48; 'down' = 0x50; 'left' = 0x4B; 'right' = 0x4D
    'a' = 0x1E; 'b' = 0x30; 'c' = 0x2E; 'd' = 0x20; 'e' = 0x12; 'f' = 0x21
    'g' = 0x22; 'h' = 0x23; 'i' = 0x17; 'j' = 0x24; 'k' = 0x25; 'l' = 0x26
    'm' = 0x32; 'n' = 0x31; 'o' = 0x18; 'p' = 0x19; 'q' = 0x10; 'r' = 0x13
    's' = 0x1F; 't' = 0x14; 'u' = 0x16; 'v' = 0x2F; 'w' = 0x11; 'x' = 0x2D
    'y' = 0x15; 'z' = 0x2C; '1' = 0x02; '2' = 0x03; '3' = 0x04; '4' = 0x05
    '5' = 0x06; '6' = 0x07; '7' = 0x08; '8' = 0x09; '9' = 0x0A; '0' = 0x0B
}
$extended = @{ 'up' = $true; 'down' = $true; 'left' = $true; 'right' = $true }

if ($PSCmdlet.ParameterSetName -eq 'Key') {
    $name = $Key.ToLowerInvariant()
    if (-not $scanCodes.ContainsKey($name)) { throw "Unknown key '$Key'." }
    $scan = [uint32]$scanCodes[$name]
    $vk = [GamePost.Native]::MapVirtualKey($scan, 3)  # MAPVK_VSC_TO_VK_EX
    $ext = if ($extended.ContainsKey($name)) { 0x01000000 } else { 0 }
    for ($i = 0; $i -lt $Repeat; $i++) {
        $down = [IntPtr](1 -bor ($scan -shl 16) -bor $ext)
        $up = [IntPtr]([int64](0xC0000001 -bor ($scan -shl 16) -bor $ext))
        [void][GamePost.Native]::PostMessage($hwnd, 0x0100, [IntPtr]$vk, $down)
        Start-Sleep -Milliseconds $HoldMs
        [void][GamePost.Native]::PostMessage($hwnd, 0x0101, [IntPtr]$vk, $up)
        if ($i + 1 -lt $Repeat) { Start-Sleep -Milliseconds 120 }
    }
    "posted=$name repeat=$Repeat hwnd=$hwnd"
    return
}

$coords = if ($PSCmdlet.ParameterSetName -eq 'Click') { $Click } else { $Move }
$parts = $coords -split ','
if ($parts.Count -ne 2) { throw "Coordinates must be 'x,y'." }
$x = [int]$parts[0]; $y = [int]$parts[1]
$lp = [IntPtr](($y -shl 16) -bor ($x -band 0xFFFF))

[void][GamePost.Native]::PostMessage($hwnd, 0x0200, [IntPtr]::Zero, $lp)
Start-Sleep -Milliseconds 60
if ($PSCmdlet.ParameterSetName -eq 'Move') { "posted move=$x,$y hwnd=$hwnd"; return }

$downMsg = if ($Button -eq 'left') { 0x0201 } else { 0x0204 }
$upMsg = if ($Button -eq 'left') { 0x0202 } else { 0x0205 }
[void][GamePost.Native]::PostMessage($hwnd, $downMsg, [IntPtr]1, $lp)
Start-Sleep -Milliseconds 90
[void][GamePost.Native]::PostMessage($hwnd, $upMsg, [IntPtr]::Zero, $lp)
"posted click=$x,$y button=$Button hwnd=$hwnd"
