param(
    [string]$Exe = "D:\Games\DiabloIII\01001B300B9BE000\01001B300B9BE000.exe",
    [string]$WorkDir = "D:\Games\DiabloIII",
    [string[]]$GameArgs = @("--fullscreen=0", "--docked=0", "--resolution=1", "--mouse_steer=0", "--touch=0"),
    [int]$Width = 1024,
    [int]$Height = 576,
    [int]$X = 40,
    [int]$Y = 40
)

# Launch the game in a small window, put it behind other windows and never make it topmost or foreground.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Add-Type -Namespace Win -Name U -MemberDefinition @"
[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
[DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr h, int cmd);
[DllImport("user32.dll")] public static extern bool SetWindowPos(System.IntPtr h, System.IntPtr after, int x, int y, int cx, int cy, uint flags);
[DllImport("user32.dll")] public static extern bool SetWindowText(System.IntPtr h, string text);
"@

[void][Win.U]::SetProcessDPIAware()
$p = Start-Process -FilePath $Exe -WorkingDirectory $WorkDir -ArgumentList $GameArgs -PassThru
"pid=$($p.Id)"
for ($i = 0; $i -lt 120; $i++) {
    Start-Sleep -Milliseconds 250
    $p.Refresh()
    if ($p.MainWindowHandle -ne [IntPtr]::Zero) { break }
}
$h = $p.MainWindowHandle
if ($h -eq [IntPtr]::Zero) { throw "window not found for pid $($p.Id)" }

# SWP_NOACTIVATE | SWP_NOZORDER | SWP_SHOWWINDOW: size and place it without focusing it.
$flags = 0x0010 -bor 0x0004 -bor 0x0040
[void][Win.U]::SetWindowPos($h, [IntPtr]::Zero, $X, $Y, $Width, $Height, $flags)
[void][Win.U]::ShowWindow($h, 4)  # SW_SHOWNOACTIVATE
"hwnd=$h size=${Width}x${Height} at $X,$Y (no activate, not topmost)"
