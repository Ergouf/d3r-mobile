param([Parameter(Mandatory)][int]$ProcessId, [string]$Keys)
Add-Type -Namespace W2 -Name U -MemberDefinition @"
[DllImport("user32.dll")] public static extern bool SetForegroundWindow(System.IntPtr h);
[DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr h, int n);
[DllImport("user32.dll")] public static extern System.IntPtr GetForegroundWindow();
[DllImport("user32.dll")] public static extern int GetWindowThreadProcessId(System.IntPtr h, out int p);
[DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool f);
[DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
[DllImport("user32.dll")] public static extern bool BringWindowToTop(System.IntPtr h);
[DllImport("user32.dll")] public static extern System.IntPtr SetFocus(System.IntPtr h);
[DllImport("user32.dll")] public static extern bool SetWindowPos(System.IntPtr h, System.IntPtr after, int x, int y, int cx, int cy, uint flags);
"@
Add-Type -AssemblyName System.Windows.Forms
$p = Get-Process -Id $ProcessId -ErrorAction Stop
$h = $p.MainWindowHandle
$me = [W2.U]::GetCurrentThreadId()
for ($attempt = 0; $attempt -lt 3; $attempt++) {
  $fg = [W2.U]::GetForegroundWindow()
  $fgPid = 0; $fgThread = [W2.U]::GetWindowThreadProcessId($fg, [ref]$fgPid)
  $targetThread = [W2.U]::GetWindowThreadProcessId($h, [ref]$fgPid)
  [void][W2.U]::AttachThreadInput($me, $fgThread, $true)
  [void][W2.U]::AttachThreadInput($me, $targetThread, $true)
  [void][W2.U]::ShowWindow($h, 9)
  [void][W2.U]::SetWindowPos($h, [System.IntPtr](-1), 0, 0, 0, 0, 0x0003)
  [void][W2.U]::SetWindowPos($h, [System.IntPtr](-2), 0, 0, 0, 0, 0x0003)
  [void][W2.U]::BringWindowToTop($h)
  [void][W2.U]::SetForegroundWindow($h)
  [void][W2.U]::SetFocus($h)
  [void][W2.U]::AttachThreadInput($me, $targetThread, $false)
  [void][W2.U]::AttachThreadInput($me, $fgThread, $false)
  Start-Sleep -Milliseconds 600
  $now = [W2.U]::GetForegroundWindow(); $nowPid = 0; [void][W2.U]::GetWindowThreadProcessId($now, [ref]$nowPid)
  if ($nowPid -eq $ProcessId) { "focused=yes attempt=$attempt"; break }
  "focused=no attempt=$attempt foreground=$nowPid"
}
Start-Sleep -Milliseconds 400
if ($Keys) { [System.Windows.Forms.SendKeys]::SendWait($Keys); "sent=$Keys" }
