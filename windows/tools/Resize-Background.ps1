param(
    [Parameter(Mandatory)][int]$ProcessId,
    [int]$Width = 1024,
    [int]$Height = 576,
    [int]$X = 40,
    [int]$Y = 40
)
# Resize and place a window without activating it and without changing its z-order.
Add-Type -Namespace W -Name U -MemberDefinition @"
[DllImport("user32.dll")] public static extern bool SetWindowPos(System.IntPtr h, System.IntPtr after, int x, int y, int cx, int cy, uint flags);
"@
$p = Get-Process -Id $ProcessId -ErrorAction Stop
$h = $p.MainWindowHandle
if ($h -eq [IntPtr]::Zero) { throw "window not found for pid $ProcessId" }
# SWP_NOACTIVATE | SWP_NOZORDER | SWP_SHOWWINDOW
[void][W.U]::SetWindowPos($h, [IntPtr]::Zero, $X, $Y, $Width, $Height, 0x0014 -bor 0x0040)
"resized hwnd=$h to ${Width}x${Height} at $X,$Y"
