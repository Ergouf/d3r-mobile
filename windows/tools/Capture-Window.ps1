param([Parameter(Mandatory)][int]$ProcessId,[Parameter(Mandatory)][string]$OutPath)
Add-Type -AssemblyName System.Drawing
Add-Type -Namespace PW -Name N -MemberDefinition @"
[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
[DllImport("user32.dll")] public static extern bool PrintWindow(System.IntPtr h, System.IntPtr dc, uint flags);
[DllImport("user32.dll")] public static extern bool GetWindowRect(System.IntPtr h, out RECT r);
[DllImport("user32.dll")] public static extern bool IsIconic(System.IntPtr h);
public struct RECT { public int L,T,R,B; }
"@
[void][PW.N]::SetProcessDPIAware()
$p=Get-Process -Id $ProcessId -ErrorAction Stop
$h=$p.MainWindowHandle
$r=New-Object PW.N+RECT
[void][PW.N]::GetWindowRect($h,[ref]$r)
"iconic=$([PW.N]::IsIconic($h)) rect=$($r.L),$($r.T),$($r.R),$($r.B)"
$w=$r.R-$r.L; $hh=$r.B-$r.T
$bmp=New-Object System.Drawing.Bitmap $w,$hh
$g=[System.Drawing.Graphics]::FromImage($bmp); $dc=$g.GetHdc()
$ok=[PW.N]::PrintWindow($h,$dc,2); $g.ReleaseHdc($dc); $g.Dispose()
$bmp.Save($OutPath,[System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
"ok=$ok saved=$OutPath"
