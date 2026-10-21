[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(60, 120)]
    [int]$RefreshHz,
    [string]$DeviceName,
    [string]$BeforePath
)

$ErrorActionPreference = 'Stop'

# Purpose-built OS display configuration, not UI automation. Only the existing
# primary 3072x1920 mode's frequency is submitted. No CDS_UPDATEREGISTRY flag.
if (-not ('DiabloWindowsDev.DisplayRefreshConfiguration' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.InteropServices;

namespace DiabloWindowsDev {
    public sealed class RefreshModeMetadata {
        public uint Width { get; set; }
        public uint Height { get; set; }
        public uint RefreshHz { get; set; }
        public uint BitsPerPixel { get; set; }
        public uint Orientation { get; set; }
        public uint FixedOutput { get; set; }
        public uint DisplayFlags { get; set; }
        public int PositionX { get; set; }
        public int PositionY { get; set; }
    }
    public sealed class RefreshPlan {
        public string DeviceName { get; set; }
        public string AdapterName { get; set; }
        public RefreshModeMetadata Before { get; set; }
        public RefreshModeMetadata SelectedExistingMode { get; set; }
        public uint SelectedEnumerationIndex { get; set; }
        internal DisplayRefreshConfiguration.DevMode NativeMode;
    }
    public static class DisplayRefreshConfiguration {
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct DisplayDevice {
            public uint Cb;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string DeviceName;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceString;
            public uint StateFlags;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceId;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceKey;
        }
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        internal struct DevMode {
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string DeviceName;
            public ushort SpecVersion, DriverVersion, Size, DriverExtra;
            public uint Fields;
            public int PositionX, PositionY;
            public uint DisplayOrientation, DisplayFixedOutput;
            public short Color, Duplex, YResolution, TTOption, Collate;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string FormName;
            public ushort LogPixels;
            public uint BitsPerPel, PelsWidth, PelsHeight, DisplayFlags, DisplayFrequency;
            public uint ICMMethod, ICMIntent, MediaType, DitherType, Reserved1, Reserved2, PanningWidth, PanningHeight;
        }
        [DllImport("user32.dll", EntryPoint = "EnumDisplayDevicesW", CharSet = CharSet.Unicode)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool EnumDisplayDevices(string device, uint index, ref DisplayDevice data, uint flags);
        [DllImport("user32.dll", EntryPoint = "EnumDisplaySettingsExW", CharSet = CharSet.Unicode)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool EnumDisplaySettingsEx(string device, int index, ref DevMode mode, uint flags);
        [DllImport("user32.dll", EntryPoint = "ChangeDisplaySettingsExW", CharSet = CharSet.Unicode)]
        private static extern int ChangeDisplaySettingsEx(string device, ref DevMode mode, IntPtr hwnd, uint flags, IntPtr reserved);

        private static DevMode Read(string device, int index) {
            DevMode mode = new DevMode { Size = (ushort)Marshal.SizeOf(typeof(DevMode)) };
            if (!EnumDisplaySettingsEx(device, index, ref mode, 0)) throw new Win32Exception("Cannot read display mode for " + device);
            return mode;
        }
        private static RefreshModeMetadata Metadata(DevMode mode) {
            return new RefreshModeMetadata {
                Width = mode.PelsWidth, Height = mode.PelsHeight, RefreshHz = mode.DisplayFrequency,
                BitsPerPixel = mode.BitsPerPel, Orientation = mode.DisplayOrientation,
                FixedOutput = mode.DisplayFixedOutput, DisplayFlags = mode.DisplayFlags,
                PositionX = mode.PositionX, PositionY = mode.PositionY
            };
        }
        public static RefreshModeMetadata ReadCurrent(string device) { return Metadata(Read(device, -1)); }
        public static RefreshPlan Prepare(uint requestedHz, string requestedDevice) {
            if (requestedHz != 60 && requestedHz != 120) throw new ArgumentOutOfRangeException("requestedHz");
            List<DisplayDevice> primary = new List<DisplayDevice>();
            for (uint i = 0; ; ++i) {
                DisplayDevice device = new DisplayDevice { Cb = (uint)Marshal.SizeOf(typeof(DisplayDevice)) };
                if (!EnumDisplayDevices(null, i, ref device, 0)) break;
                if ((device.StateFlags & 1) != 0 && (device.StateFlags & 4) != 0 && (device.StateFlags & 8) == 0) primary.Add(device);
            }
            if (primary.Count != 1) throw new InvalidOperationException("Expected exactly one attached primary display.");
            DisplayDevice target = primary[0];
            if (!String.IsNullOrEmpty(requestedDevice) && !String.Equals(requestedDevice, target.DeviceName, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Requested device is not the primary display: " + target.DeviceName);
            DevMode current = Read(target.DeviceName, -1);
            if (current.PelsWidth != 3072 || current.PelsHeight != 1920)
                throw new InvalidOperationException("Refusing: current primary mode is not 3072x1920.");
            List<uint> available = new List<uint>();
            for (int i = 0; ; ++i) {
                DevMode mode = new DevMode { Size = (ushort)Marshal.SizeOf(typeof(DevMode)) };
                if (!EnumDisplaySettingsEx(target.DeviceName, i, ref mode, 0)) break;
                if (mode.PelsWidth != current.PelsWidth || mode.PelsHeight != current.PelsHeight ||
                    mode.BitsPerPel != current.BitsPerPel || mode.DisplayOrientation != current.DisplayOrientation ||
                    mode.DisplayFlags != current.DisplayFlags || mode.DisplayFixedOutput != current.DisplayFixedOutput) continue;
                if (!available.Contains(mode.DisplayFrequency)) available.Add(mode.DisplayFrequency);
                if (mode.DisplayFrequency != requestedHz) continue;
                RefreshPlan plan = new RefreshPlan {
                    DeviceName = target.DeviceName, AdapterName = target.DeviceString, Before = Metadata(current),
                    SelectedExistingMode = Metadata(mode), SelectedEnumerationIndex = (uint)i, NativeMode = mode
                };
                // DM_DISPLAYFREQUENCY only. Resolution, color depth, orientation and position are never submitted.
                plan.NativeMode.Fields = 0x00400000;
                plan.NativeMode.DriverExtra = 0;
                return plan;
            }
            throw new InvalidOperationException("No matching existing " + requestedHz + " Hz mode; same-size/color/orientation frequencies: " + String.Join(", ", available));
        }
        public static int Test(RefreshPlan plan) {
            DevMode mode = plan.NativeMode;
            return ChangeDisplaySettingsEx(plan.DeviceName, ref mode, IntPtr.Zero, 0x00000002, IntPtr.Zero); // CDS_TEST
        }
        public static int ApplyTemporary(RefreshPlan plan) {
            DevMode mode = plan.NativeMode;
            return ChangeDisplaySettingsEx(plan.DeviceName, ref mode, IntPtr.Zero, 0, IntPtr.Zero);
        }
    }
}
'@
}

$refreshPlan = [DiabloWindowsDev.DisplayRefreshConfiguration]::Prepare([uint32]$RefreshHz, $DeviceName)
$displayReaderPath = Join-Path $PSScriptRoot 'Get-ActiveDisplayMode.ps1'
$beforeDisplays = @(& $displayReaderPath)
$beforePrimary = @($beforeDisplays | Where-Object { $_.GdiDeviceName -ieq $refreshPlan.DeviceName })
if ($beforePrimary.Count -ne 1 -or $beforePrimary[0].QueryMethod -ne 'QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS)') {
    throw 'Cannot independently read the primary active physical path; refusing to apply a mode.'
}
if ($beforePrimary[0].DesktopSize.Width -ne 3072 -or $beforePrimary[0].DesktopSize.Height -ne 1920) {
    throw 'Active desktop size does not match the required 3072x1920 mode.'
}
$restoreRefreshHz = [int][Math]::Round($beforePrimary[0].SignalVSyncRate.Hz)
if ($restoreRefreshHz -notin @(60, 120) -or
    [Math]::Abs($beforePrimary[0].SignalVSyncRate.Hz - $restoreRefreshHz) -ge 0.1) {
    throw 'Current exact signal rate is outside the supported 60/120 Hz restoration pair.'
}
$testResult = [DiabloWindowsDev.DisplayRefreshConfiguration]::Test($refreshPlan)
if ($testResult -ne 0) { throw "CDS_TEST rejected the existing mode (DISP_CHANGE=$testResult). No mode was changed." }

$refreshDescription = '{0}: existing 3072x1920 @{1} Hz; only DM_DISPLAYFREQUENCY, flags=0, no registry write' -f $refreshPlan.DeviceName, $RefreshHz
if (-not $PSCmdlet.ShouldProcess($refreshDescription, 'Temporarily apply display refresh rate')) {
    [pscustomobject]@{
        Applied = $false
        TestResult = $testResult
        Plan = $refreshPlan
        BeforeActiveDisplay = $beforePrimary[0]
        Note = 'Enumeration and CDS_TEST only; no display settings or snapshot files changed.'
    }
    return
}

# Persist identity and exact pre-change QueryDisplayConfig rationals before any mode change.
if (-not $BeforePath) {
    $refreshEvidenceRoot = Join-Path $PSScriptRoot '..\..\out\windows\display-mode'
    $BeforePath = Join-Path $refreshEvidenceRoot ('before-{0}-{1}.json' -f (Get-Date -Format 'yyyyMMdd-HHmmss-fff'), ([guid]::NewGuid().ToString('N').Substring(0, 8)))
}
$refreshSnapshotPath = [IO.Path]::GetFullPath($BeforePath)
$null = New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($refreshSnapshotPath)) -Force
$refreshSnapshot = [ordered]@{
    CapturedAt = [DateTimeOffset]::Now.ToString('o')
    IntendedRefreshHz = $RefreshHz
    ConfigurationFlags = 0
    ConfigurationFields = 'DM_DISPLAYFREQUENCY only'
    Plan = $refreshPlan
    BeforeActiveDisplays = $beforeDisplays
    RestoreRefreshHz = $restoreRefreshHz
    RestoreCommand = ".\tools\windows-dev\Set-ActiveDisplayRefresh.ps1 -RefreshHz $restoreRefreshHz -DeviceName '$($refreshPlan.DeviceName)'"
}
$refreshStream = [IO.File]::Open($refreshSnapshotPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
try {
    $refreshWriter = [IO.StreamWriter]::new($refreshStream, [Text.UTF8Encoding]::new($false))
    try { $refreshWriter.Write(($refreshSnapshot | ConvertTo-Json -Depth 10)) }
    finally { $refreshWriter.Dispose() }
} finally { $refreshStream.Dispose() }

$applyResult = [DiabloWindowsDev.DisplayRefreshConfiguration]::ApplyTemporary($refreshPlan)
if ($applyResult -ne 0) { throw "Temporary mode change failed (DISP_CHANGE=$applyResult). Before metadata: $refreshSnapshotPath" }

$afterPrimary = @()
for ($refreshReadAttempt = 0; $refreshReadAttempt -lt 8; ++$refreshReadAttempt) {
    if ($refreshReadAttempt -gt 0) { Start-Sleep -Milliseconds 200 }
    $afterPrimary = @((& $displayReaderPath) | Where-Object { $_.GdiDeviceName -ieq $refreshPlan.DeviceName })
    if ($afterPrimary.Count -eq 1 -and
        $afterPrimary[0].QueryMethod -eq 'QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS)' -and
        $null -ne $afterPrimary[0].SignalVSyncRate.Hz -and
        [Math]::Abs($afterPrimary[0].SignalVSyncRate.Hz - $RefreshHz) -lt 0.1 -and
        [Math]::Abs($afterPrimary[0].PathRefreshRate.Hz - $RefreshHz) -lt 0.1) { break }
}
$afterCurrent = [DiabloWindowsDev.DisplayRefreshConfiguration]::ReadCurrent($refreshPlan.DeviceName)
$verified = $afterPrimary.Count -eq 1 -and
    $afterPrimary[0].QueryMethod -eq 'QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS)' -and
    $null -ne $afterPrimary[0].SignalVSyncRate.Hz -and
    [Math]::Abs($afterPrimary[0].SignalVSyncRate.Hz - $RefreshHz) -lt 0.1 -and
    [Math]::Abs($afterPrimary[0].PathRefreshRate.Hz - $RefreshHz) -lt 0.1 -and
    $afterPrimary[0].DesktopSize.Width -eq 3072 -and $afterPrimary[0].DesktopSize.Height -eq 1920 -and
    $afterPrimary[0].ActiveSignalSize.Width -eq $beforePrimary[0].ActiveSignalSize.Width -and
    $afterPrimary[0].ActiveSignalSize.Height -eq $beforePrimary[0].ActiveSignalSize.Height -and
    $afterCurrent.BitsPerPixel -eq $refreshPlan.Before.BitsPerPixel -and
    $afterCurrent.Orientation -eq $refreshPlan.Before.Orientation -and
    $afterCurrent.FixedOutput -eq $refreshPlan.Before.FixedOutput -and
    $afterCurrent.DisplayFlags -eq $refreshPlan.Before.DisplayFlags -and
    $afterCurrent.PositionX -eq $refreshPlan.Before.PositionX -and $afterCurrent.PositionY -eq $refreshPlan.Before.PositionY
if (-not $verified) {
    throw "Mode API returned success, but refresh/resolution/color/orientation verification failed. Before metadata: $refreshSnapshotPath"
}
[pscustomobject]@{
    Applied = $true
    Verified = $true
    TestResult = $testResult
    ApplyResult = $applyResult
    BeforeMetadataPath = $refreshSnapshotPath
    RestoreCommand = $refreshSnapshot.RestoreCommand
    BeforeActiveDisplay = $beforePrimary[0]
    AfterActiveDisplay = $afterPrimary[0]
    Note = 'Temporary OS configuration (flags=0); registry, resolution, color depth and orientation unchanged.'
}
