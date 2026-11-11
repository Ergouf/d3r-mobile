param([Parameter(Mandatory)][string]$OutPath, [int]$CropX=-1, [int]$CropY=-1, [int]$CropW=0, [int]$CropH=0)
Add-Type -Namespace D -Name P -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
[void][D.P]::SetProcessDPIAware()
Add-Type -AssemblyName System.Drawing,System.Windows.Forms
$b=[System.Windows.Forms.SystemInformation]::VirtualScreen
"virtual=$($b.Width)x$($b.Height) at $($b.Left),$($b.Top)"
$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height
$g=[System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Left,$b.Top,0,0,$bmp.Size); $g.Dispose()
if ($CropW -gt 0) {
  $rect=New-Object System.Drawing.Rectangle $CropX,$CropY,$CropW,$CropH
  $c=$bmp.Clone($rect,$bmp.PixelFormat); $c.Save($OutPath,[System.Drawing.Imaging.ImageFormat]::Png); $c.Dispose()
} else { $bmp.Save($OutPath,[System.Drawing.Imaging.ImageFormat]::Png) }
$bmp.Dispose()
"saved=$OutPath"
