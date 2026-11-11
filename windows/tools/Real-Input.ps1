param(
    [string]$Key,
    [string]$Click,
    [string]$Move,
    [string]$Button = "left",
    [int]$HoldMs = 60,
    [switch]$Screen,
    [int]$ProcessId = 0,
    [switch]$Focus
)
# Real keyboard/mouse input (user authorisation 2026-11-01 night). Keys go to the focused window, so focus the
# game first (Focus-Capture.ps1). Click/Move coordinates are pixels of the whole window (the same frame the
# screenshots use); -Screen uses absolute desktop pixels instead.
# Kept in windows/tools/ so committed probes do not depend on the ignored out/ tree.
$ErrorActionPreference = 'Stop'
Add-Type -Namespace Inp -Name W -MemberDefinition @"
[StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
[DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
[DllImport("user32.dll")] public static extern void mouse_event(uint flags, int dx, int dy, uint data, System.UIntPtr extra);
[DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, System.UIntPtr extra);
[DllImport("user32.dll")] public static extern bool GetWindowRect(System.IntPtr h, out RECT r);
[DllImport("user32.dll")] public static extern System.IntPtr GetForegroundWindow();
[DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(System.IntPtr h, out uint pid);
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(System.IntPtr h);
[DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr h, int cmd);
[DllImport("user32.dll")] public static extern int MapVirtualKeyA(uint code, uint mapType);
[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
"@
[void][Inp.W]::SetProcessDPIAware()
function Get-GameWindow {
    $p = Get-Process | Where-Object { ($ProcessId -eq 0 -or $_.Id -eq $ProcessId) -and $_.ProcessName -match '^[0-9a-fA-F]{16}$' } |
         Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
    if (-not $p) { throw "no game window" }
    if ($Focus) {
        # Explicit opt-in under the user's 2026-11-01 foreground/input authorization.
        [void][Inp.W]::ShowWindow($p.MainWindowHandle, 9)
        [void][Inp.W]::SetForegroundWindow($p.MainWindowHandle)
        Start-Sleep -Milliseconds 150
    }
    return $p.MainWindowHandle
}
$vk = @{
    ' ' = 0x20; 'space' = 0x20; 'esc' = 0x1B; 'enter' = 0x0D; 'return' = 0x0D; 'tab' = 0x09;
    'shift' = 0x10; 'ctrl' = 0x11; 'alt' = 0x12; 'back' = 0x08;
    'left' = 0x25; 'up' = 0x26; 'right' = 0x27; 'down' = 0x28;
}
if ($Key) {
    $k = $Key.ToLower()
    if ($vk.ContainsKey($k)) { $code = $vk[$k] }
    elseif ($k.Length -eq 1 -and $k -match '[a-z0-9]') { $code = [int][char]$k.ToUpper() }
    else { throw "unknown key '$Key'" }
    $hwnd = Get-GameWindow
    if ([Inp.W]::GetForegroundWindow() -ne $hwnd) {
        [uint32]$kbmForegroundPid = 0
        [void][Inp.W]::GetWindowThreadProcessId([Inp.W]::GetForegroundWindow(), [ref]$kbmForegroundPid)
        throw "game window is not focused (foreground pid=$kbmForegroundPid)"
    }
    $scan = [Inp.W]::MapVirtualKeyA($code, 0)
    [Inp.W]::keybd_event([byte]$code, [byte]$scan, 0, [System.UIntPtr]::Zero)
    try { Start-Sleep -Milliseconds $HoldMs }
    finally { [Inp.W]::keybd_event([byte]$code, [byte]$scan, 2, [System.UIntPtr]::Zero) }
    "key=$k vk=0x$($code.ToString('x2')) hold=${HoldMs}ms"
}
elseif ($Click -or $Move) {
    $hwnd = Get-GameWindow
    $spec = if ($Click) { $Click } else { $Move }
    $parts = $spec.Split(',')
    $x = [int]$parts[0]; $y = [int]$parts[1]
    $r = New-Object Inp.W+RECT
    [void][Inp.W]::GetWindowRect($hwnd, [ref]$r)
    if (-not $Screen) { $x = $r.Left + $x; $y = $r.Top + $y }
    if ($x -lt $r.Left -or $x -ge $r.Right -or $y -lt $r.Top -or $y -ge $r.Bottom) {
        throw "point $x,$y is outside the game window $($r.Left),$($r.Top),$($r.Right),$($r.Bottom)"
    }
    [void][Inp.W]::SetCursorPos($x, $y)
    Start-Sleep -Milliseconds 120
    if ($Click) {
        $down = 0x0002; $up = 0x0004
        if ($Button -eq 'right') { $down = 0x0008; $up = 0x0010 }
        elseif ($Button -eq 'middle') { $down = 0x0020; $up = 0x0040 }
        [Inp.W]::mouse_event($down, 0, 0, 0, [System.UIntPtr]::Zero)
        Start-Sleep -Milliseconds $HoldMs
        [Inp.W]::mouse_event($up, 0, 0, 0, [System.UIntPtr]::Zero)
        "click $Button at screen $x,$y"
    } else {
        "move to screen $x,$y"
    }
}
else { throw "nothing to do: pass -Key, -Click or -Move" }
