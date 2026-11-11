[CmdletBinding()]
param([switch]$AsJson)

$ErrorActionPreference = 'Stop'

# Read-only Win32 queries. No SetDisplayConfig / ChangeDisplaySettings calls.
if (-not ('DiabloWindowsDev.ActiveDisplayReader' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.InteropServices;

namespace DiabloWindowsDev {
    public sealed class DisplayRate {
        public uint Numerator { get; set; }
        public uint Denominator { get; set; }
        public double? Hz { get { return Denominator == 0 ? (double?)null : (double)Numerator / Denominator; } }
    }
    public sealed class DisplayExtent {
        public uint Width { get; set; }
        public uint Height { get; set; }
    }
    public sealed class ActiveDisplay {
        public string QueryMethod { get; set; }
        public string QueryWarning { get; set; }
        public string GdiDeviceName { get; set; }
        public string AdapterName { get; set; }
        public string AdapterDevicePath { get; set; }
        public string AdapterLuid { get; set; }
        public uint SourceId { get; set; }
        public uint TargetId { get; set; }
        public string MonitorName { get; set; }
        public string MonitorDevicePath { get; set; }
        public DisplayExtent DesktopSize { get; set; }
        public DisplayExtent ActiveSignalSize { get; set; }
        public DisplayExtent TotalSignalSize { get; set; }
        public DisplayRate PathRefreshRate { get; set; }
        public DisplayRate SignalVSyncRate { get; set; }
        public DisplayRate SignalHSyncRate { get; set; }
        public ulong? PixelRate { get; set; }
        public string OutputTechnology { get; set; }
        public uint Rotation { get; set; }
        public uint ScanLineOrdering { get; set; }
        public uint PathFlags { get; set; }
    }

    public static class ActiveDisplayReader {
        private const uint QDC_ONLY_ACTIVE_PATHS = 0x2;
        private const int ERROR_INSUFFICIENT_BUFFER = 122;
        [StructLayout(LayoutKind.Sequential)] private struct Luid { public uint Low; public int High; }
        [StructLayout(LayoutKind.Sequential)] private struct Rational { public uint Numerator, Denominator; }
        [StructLayout(LayoutKind.Sequential)] private struct Region { public uint Width, Height; }
        [StructLayout(LayoutKind.Sequential)] private struct SignalInfo {
            public ulong PixelRate;
            public Rational HSyncFreq, VSyncFreq;
            public Region ActiveSize, TotalSize;
            public uint VideoStandard, ScanLineOrdering;
        }
        [StructLayout(LayoutKind.Sequential)] private struct SourceMode {
            public uint Width, Height, PixelFormat;
            public int X, Y;
        }
        [StructLayout(LayoutKind.Explicit, Size = 64)] private struct ModeInfo {
            [FieldOffset(0)] public uint InfoType;
            [FieldOffset(4)] public uint Id;
            [FieldOffset(8)] public Luid AdapterId;
            [FieldOffset(16)] public SignalInfo Target;
            [FieldOffset(16)] public SourceMode Source;
        }
        [StructLayout(LayoutKind.Sequential)] private struct PathSource {
            public Luid AdapterId;
            public uint Id, ModeInfoIdx, StatusFlags;
        }
        [StructLayout(LayoutKind.Sequential)] private struct PathTarget {
            public Luid AdapterId;
            public uint Id, ModeInfoIdx, OutputTechnology, Rotation, Scaling;
            public Rational RefreshRate;
            public uint ScanLineOrdering;
            public int TargetAvailable;
            public uint StatusFlags;
        }
        [StructLayout(LayoutKind.Sequential)] private struct PathInfo {
            public PathSource Source;
            public PathTarget Target;
            public uint Flags;
        }
        [StructLayout(LayoutKind.Sequential)] private struct DeviceInfoHeader {
            public uint Type, Size;
            public Luid AdapterId;
            public uint Id;
        }
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] private struct SourceName {
            public DeviceInfoHeader Header;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string GdiDeviceName;
        }
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] private struct TargetName {
            public DeviceInfoHeader Header;
            public uint Flags, OutputTechnology;
            public ushort EdidManufactureId, EdidProductCodeId;
            public uint ConnectorInstance;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 64)] public string FriendlyName;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DevicePath;
        }
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] private struct AdapterName {
            public DeviceInfoHeader Header;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DevicePath;
        }
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] private struct DisplayDevice {
            public uint Cb;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string DeviceName;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceString;
            public uint StateFlags;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceId;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceKey;
        }
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] private struct DevMode {
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

        [DllImport("user32.dll")] private static extern int GetDisplayConfigBufferSizes(uint flags, out uint pathCount, out uint modeCount);
        [DllImport("user32.dll")] private static extern int QueryDisplayConfig(uint flags, ref uint pathCount, [Out] PathInfo[] paths, ref uint modeCount, [Out] ModeInfo[] modes, IntPtr topologyId);
        [DllImport("user32.dll", EntryPoint = "DisplayConfigGetDeviceInfo")] private static extern int GetSourceName(ref SourceName data);
        [DllImport("user32.dll", EntryPoint = "DisplayConfigGetDeviceInfo")] private static extern int GetTargetName(ref TargetName data);
        [DllImport("user32.dll", EntryPoint = "DisplayConfigGetDeviceInfo")] private static extern int GetAdapterName(ref AdapterName data);
        [DllImport("user32.dll", EntryPoint = "EnumDisplayDevicesW", CharSet = CharSet.Unicode)]
        [return: MarshalAs(UnmanagedType.Bool)] private static extern bool EnumDisplayDevices(string device, uint index, ref DisplayDevice data, uint flags);
        [DllImport("user32.dll", EntryPoint = "EnumDisplaySettingsExW", CharSet = CharSet.Unicode)]
        [return: MarshalAs(UnmanagedType.Bool)] private static extern bool EnumDisplaySettingsEx(string device, int mode, ref DevMode data, uint flags);

        private static DeviceInfoHeader Header(uint type, int size, Luid adapter, uint id) {
            return new DeviceInfoHeader { Type = type, Size = (uint)size, AdapterId = adapter, Id = id };
        }
        private static DisplayRate Rate(Rational value) {
            return new DisplayRate { Numerator = value.Numerator, Denominator = value.Denominator };
        }
        private static DisplayExtent Extent(Region value) {
            return new DisplayExtent { Width = value.Width, Height = value.Height };
        }
        private static List<DisplayDevice> Adapters() {
            List<DisplayDevice> result = new List<DisplayDevice>();
            for (uint i = 0; ; ++i) {
                DisplayDevice item = new DisplayDevice { Cb = (uint)Marshal.SizeOf(typeof(DisplayDevice)) };
                if (!EnumDisplayDevices(null, i, ref item, 0)) break;
                result.Add(item);
            }
            return result;
        }
        private static string OutputName(uint value) {
            switch (value) {
                case 0: return "HD15";
                case 4: return "DVI";
                case 5: return "HDMI";
                case 6: return "LVDS";
                case 10: return "DisplayPort external";
                case 11: return "DisplayPort embedded";
                case 12: return "UDI external";
                case 13: return "UDI embedded";
                case 15: return "Miracast";
                case 16: return "Indirect wired";
                case 17: return "Indirect virtual";
                case 0x80000000: return "Internal";
                default: return "Value " + value;
            }
        }
        public static ActiveDisplay[] Read() {
            int failure = 0;
            for (int attempt = 0; attempt < 4; ++attempt) {
                uint pathCount, modeCount;
                failure = GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, out pathCount, out modeCount);
                if (failure != 0) break;
                PathInfo[] paths = new PathInfo[pathCount];
                ModeInfo[] modes = new ModeInfo[modeCount];
                failure = QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, ref pathCount, paths, ref modeCount, modes, IntPtr.Zero);
                if (failure == ERROR_INSUFFICIENT_BUFFER) continue;
                if (failure != 0) break;
                List<ActiveDisplay> result = new List<ActiveDisplay>();
                List<DisplayDevice> adapters = Adapters();
                for (uint i = 0; i < pathCount; ++i) {
                    PathInfo path = paths[i];
                    SourceName source = new SourceName { Header = Header(1, Marshal.SizeOf(typeof(SourceName)), path.Source.AdapterId, path.Source.Id) };
                    TargetName target = new TargetName { Header = Header(2, Marshal.SizeOf(typeof(TargetName)), path.Target.AdapterId, path.Target.Id) };
                    AdapterName adapter = new AdapterName { Header = Header(4, Marshal.SizeOf(typeof(AdapterName)), path.Source.AdapterId, path.Source.Id) };
                    int sourceError = GetSourceName(ref source);
                    int targetError = GetTargetName(ref target);
                    int adapterError = GetAdapterName(ref adapter);
                    ActiveDisplay item = new ActiveDisplay {
                        QueryMethod = "QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS)",
                        GdiDeviceName = sourceError == 0 ? source.GdiDeviceName : null,
                        AdapterDevicePath = adapterError == 0 ? adapter.DevicePath : null,
                        AdapterLuid = String.Format("{0:x8}:{1:x8}", unchecked((uint)path.Source.AdapterId.High), path.Source.AdapterId.Low),
                        SourceId = path.Source.Id, TargetId = path.Target.Id,
                        MonitorName = targetError == 0 ? target.FriendlyName : null,
                        MonitorDevicePath = targetError == 0 ? target.DevicePath : null,
                        PathRefreshRate = Rate(path.Target.RefreshRate),
                        OutputTechnology = OutputName(path.Target.OutputTechnology),
                        Rotation = path.Target.Rotation, ScanLineOrdering = path.Target.ScanLineOrdering, PathFlags = path.Flags
                    };
                    foreach (DisplayDevice candidate in adapters) {
                        if (String.Equals(candidate.DeviceName, item.GdiDeviceName, StringComparison.OrdinalIgnoreCase)) {
                            item.AdapterName = candidate.DeviceString;
                            break;
                        }
                    }
                    if (path.Source.ModeInfoIdx < modeCount && modes[path.Source.ModeInfoIdx].InfoType == 1) {
                        SourceMode mode = modes[path.Source.ModeInfoIdx].Source;
                        item.DesktopSize = new DisplayExtent { Width = mode.Width, Height = mode.Height };
                    }
                    if (path.Target.ModeInfoIdx < modeCount && modes[path.Target.ModeInfoIdx].InfoType == 2) {
                        SignalInfo signal = modes[path.Target.ModeInfoIdx].Target;
                        item.ActiveSignalSize = Extent(signal.ActiveSize);
                        item.TotalSignalSize = Extent(signal.TotalSize);
                        item.SignalVSyncRate = Rate(signal.VSyncFreq);
                        item.SignalHSyncRate = Rate(signal.HSyncFreq);
                        item.PixelRate = signal.PixelRate;
                    }
                    if (sourceError != 0 || targetError != 0 || adapterError != 0) {
                        item.QueryWarning = String.Format("Device-name query status: source={0}, target={1}, adapter={2}; mode data remains from QueryDisplayConfig.", sourceError, targetError, adapterError);
                    }
                    result.Add(item);
                }
                return result.ToArray();
            }
            return Fallback(failure);
        }
        private static ActiveDisplay[] Fallback(int failure) {
            List<ActiveDisplay> result = new List<ActiveDisplay>();
            foreach (DisplayDevice adapter in Adapters()) {
                if ((adapter.StateFlags & 1) == 0 || (adapter.StateFlags & 8) != 0) continue;
                DevMode mode = new DevMode { Size = (ushort)Marshal.SizeOf(typeof(DevMode)) };
                if (!EnumDisplaySettingsEx(adapter.DeviceName, -1, ref mode, 0)) continue;
                result.Add(new ActiveDisplay {
                    QueryMethod = "EnumDisplaySettingsEx(ENUM_CURRENT_SETTINGS) fallback",
                    QueryWarning = String.Format("QueryDisplayConfig failed: {0} ({1}); fallback frequency is integer-only and is not an exact physical signal measurement.", failure, new Win32Exception(failure).Message),
                    GdiDeviceName = adapter.DeviceName, AdapterName = adapter.DeviceString,
                    DesktopSize = new DisplayExtent { Width = mode.PelsWidth, Height = mode.PelsHeight },
                    PathRefreshRate = new DisplayRate { Numerator = mode.DisplayFrequency, Denominator = 1 }
                });
            }
            if (result.Count == 0) throw new Win32Exception(failure, "QueryDisplayConfig failed and no current GDI mode could be read.");
            return result.ToArray();
        }
    }
}
'@
}

$displayModes = [DiabloWindowsDev.ActiveDisplayReader]::Read()
if ($AsJson) {
    ConvertTo-Json -InputObject @($displayModes) -Depth 7
} else {
    $displayModes
}
