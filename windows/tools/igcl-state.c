/* Read-only Intel Graphics Control Library state query. No rendering or setting writes.
   Build: clang -std=c11 -O2 -Wall -Wextra -Werror -Ilocal/tools/igcl
          windows/tools/igcl-state.c -o out/windows/igcl-state.exe
   SDK provenance/license: local/tools/igcl/SOURCE.json and LICENSE. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
/* The unmodified SDK exports declarations by default; this executable dynamically resolves getters. */
#define CTL_APIEXPORT
#include "igcl_api.h"

typedef struct {
    ctl_pfnInit_t init;
    ctl_pfnClose_t close;
    ctl_pfnEnumerateDevices_t devices;
    ctl_pfnEnumerateDisplayOutputs_t displays;
    ctl_pfnGetDeviceProperties_t device_properties;
    ctl_pfnGetDisplayProperties_t display_properties;
    ctl_pfnGetSupported3DCapabilities_t feature_caps;
    ctl_pfnGetSet3DFeature_t get_feature;
    ctl_pfnGetIntelArcSyncInfoForMonitor_t arc_caps;
    ctl_pfnGetIntelArcSyncProfile_t arc_profile;
} ReadApi;

#define LOAD_GETTER(member, name) do { \
    FARPROC address = GetProcAddress(module, name); \
    _Static_assert(sizeof api.member == sizeof address, "Windows function pointer size"); \
    memcpy(&api.member, &address, sizeof address); \
    if (!address) printf("unsupported: missing export %s\n", name); \
} while (0)

static bool result_ok(const char* call, ctl_result_t result) {
    printf("%s rc=0x%08X\n", call, (unsigned)result);
    return result == CTL_RESULT_SUCCESS;
}

/* Follow the official two-pass capability sample; custom data is requested only for ASP. */
static int print_asp_caps(const ReadApi* api, ctl_device_adapter_handle_t device) {
    if (!api->feature_caps) return -1;
    ctl_3d_feature_caps_t caps = {0};
    caps.Size = sizeof caps;
    caps.Version = 0;
    if (!result_ok("ctlGetSupported3DCapabilities/count", api->feature_caps(device, &caps))) return -1;
    if (!caps.NumSupportedFeatures || caps.NumSupportedFeatures > 4096) {
        printf("ASP capability unavailable: feature_count=%u\n", (unsigned)caps.NumSupportedFeatures);
        return -1;
    }
    uint32_t capacity = caps.NumSupportedFeatures;
    ctl_3d_feature_details_t* details = calloc(capacity, sizeof *details);
    if (!details) { puts("ASP capability unavailable: allocation failed"); return -1; }
    caps.pFeatureDetails = details;
    int per_app = -1;
    if (result_ok("ctlGetSupported3DCapabilities/details", api->feature_caps(device, &caps))) {
        uint32_t count = caps.NumSupportedFeatures < capacity ? caps.NumSupportedFeatures : capacity;
        bool found = false;
        for (uint32_t i = 0; i < count; i++) {
            if (details[i].FeatureType != CTL_3D_FEATURE_ADAPTIVE_SYNC_PLUS) continue;
            found = true;
            per_app = details[i].PerAppSupport ? 1 : 0;
            printf("ASP caps: per_app=%d value_type=%u custom_size=%d api_flags=0x%X vulkan=%d\n",
                   per_app, (unsigned)details[i].ValueType, (int)details[i].CustomValueSize,
                   (unsigned)(uint16_t)details[i].FeatureMiscSupport,
                   !!(details[i].FeatureMiscSupport & CTL_3D_FEATURE_MISC_FLAG_VULKAN));
            ctl_adaptivesync_caps_t custom = {0};
            ctl_3d_feature_details_t detail = details[i];
            detail.CustomValueSize = sizeof custom;
            detail.pCustomValue = &custom;
            ctl_3d_feature_caps_t one = {0};
            one.Size = sizeof one;
            one.Version = 0;
            one.NumSupportedFeatures = 1;
            one.pFeatureDetails = &detail;
            if (detail.ValueType == CTL_PROPERTY_VALUE_TYPE_CUSTOM &&
                result_ok("ctlGetSupported3DCapabilities/ASP", api->feature_caps(device, &one)))
                printf("ASP caps: AdaptiveBalanceSupported=%d\n", custom.AdaptiveBalanceSupported ? 1 : 0);
        }
        if (!found) puts("ASP capability not advertised; direct getter may return unsupported");
    }
    free(details);
    return per_app;
}

static void print_asp(const ReadApi* api, ctl_device_adapter_handle_t device, char* application) {
    if (!api->get_feature) return;
    ctl_adaptivesync_getset_t state = {0};
    ctl_3d_feature_getset_t query = {0};
    query.Size = sizeof query;
    query.Version = 0;
    query.FeatureType = CTL_3D_FEATURE_ADAPTIVE_SYNC_PLUS;
    query.ApplicationName = application;
    query.ApplicationNameLength = (int8_t)strlen(application);
    query.bSet = false; /* This tool has no set operation or command-line setting controls. */
    query.ValueType = CTL_PROPERTY_VALUE_TYPE_CUSTOM;
    query.CustomValueSize = sizeof state;
    query.pCustomValue = &state;
    printf("ASP query: application=%s bSet=false\n", *application ? application : "<global>");
    if (result_ok("ctlGetSet3DFeature/get-only", api->get_feature(device, &query)))
        printf("ASP configured: AdaptiveSync=%d AdaptiveBalance=%d AllowAsyncForHighFPS=%d "
               "AdaptiveBalanceStrength=%.6f\n", state.AdaptiveSync ? 1 : 0, state.AdaptiveBalance ? 1 : 0,
               state.AllowAsyncForHighFPS ? 1 : 0, (double)state.AdaptiveBalanceStrength);
}

static const char* profile_name(ctl_intel_arc_sync_profile_t profile) {
    switch (profile) {
        case CTL_INTEL_ARC_SYNC_PROFILE_RECOMMENDED: return "RECOMMENDED";
        case CTL_INTEL_ARC_SYNC_PROFILE_EXCELLENT: return "EXCELLENT";
        case CTL_INTEL_ARC_SYNC_PROFILE_GOOD: return "GOOD";
        case CTL_INTEL_ARC_SYNC_PROFILE_COMPATIBLE: return "COMPATIBLE";
        case CTL_INTEL_ARC_SYNC_PROFILE_OFF: return "OFF";
        case CTL_INTEL_ARC_SYNC_PROFILE_VESA: return "VESA";
        case CTL_INTEL_ARC_SYNC_PROFILE_CUSTOM: return "CUSTOM";
        default: return "INVALID_OR_UNKNOWN";
    }
}

static void print_displays(const ReadApi* api, ctl_device_adapter_handle_t device) {
    if (!api->displays) return;
    uint32_t count = 0;
    if (!result_ok("ctlEnumerateDisplayOutputs/count", api->displays(device, &count, NULL))) return;
    if (!count || count > 512) { printf("display_count=%u; no outputs queried\n", (unsigned)count); return; }
    uint32_t capacity = count;
    ctl_display_output_handle_t* displays = calloc(capacity, sizeof *displays);
    if (!displays) { puts("display enumeration allocation failed"); return; }
    if (!result_ok("ctlEnumerateDisplayOutputs/list", api->displays(device, &count, displays))) {
        free(displays); return;
    }
    if (count > capacity) count = capacity;
    for (uint32_t i = 0; i < count; i++) {
        printf("display[%u]\n", (unsigned)i);
        if (api->display_properties) {
            ctl_display_properties_t p = {0};
            p.Size = sizeof p;
            p.Version = 0;
            p.Display_Timing_Info.Size = sizeof p.Display_Timing_Info;
            p.Display_Timing_Info.Version = 0;
            if (result_ok("ctlGetDisplayProperties", api->display_properties(displays[i], &p)))
                printf("display: type=%u active=%d attached=%d mode=%ux%u@%.6f "
                       "VRR_supported=%d VRR_enabled=%d feature_supported=0x%X feature_enabled=0x%X\n",
                       (unsigned)p.Type, !!(p.DisplayConfigFlags & CTL_DISPLAY_CONFIG_FLAG_DISPLAY_ACTIVE),
                       !!(p.DisplayConfigFlags & CTL_DISPLAY_CONFIG_FLAG_DISPLAY_ATTACHED),
                       (unsigned)p.Display_Timing_Info.HActive, (unsigned)p.Display_Timing_Info.VActive,
                       (double)p.Display_Timing_Info.RefreshRate,
                       !!(p.FeatureSupportedFlags & CTL_STD_DISPLAY_FEATURE_FLAG_ADAPTIVESYNC_VRR),
                       !!(p.FeatureEnabledFlags & CTL_STD_DISPLAY_FEATURE_FLAG_ADAPTIVESYNC_VRR),
                       (unsigned)p.FeatureSupportedFlags, (unsigned)p.FeatureEnabledFlags);
        }
        if (api->arc_caps) {
            ctl_intel_arc_sync_monitor_params_t caps = {0};
            caps.Size = sizeof caps;
            caps.Version = 0;
            if (result_ok("ctlGetIntelArcSyncInfoForMonitor", api->arc_caps(displays[i], &caps)))
                printf("ArcSync caps: supported=%d min_Hz=%.6f max_Hz=%.6f increase_us=%u decrease_us=%u\n",
                       caps.IsIntelArcSyncSupported ? 1 : 0, (double)caps.MinimumRefreshRateInHz,
                       (double)caps.MaximumRefreshRateInHz, (unsigned)caps.MaxFrameTimeIncreaseInUs,
                       (unsigned)caps.MaxFrameTimeDecreaseInUs);
        }
        if (api->arc_profile) {
            ctl_intel_arc_sync_profile_params_t profile = {0};
            profile.Size = sizeof profile;
            profile.Version = 0;
            if (result_ok("ctlGetIntelArcSyncProfile", api->arc_profile(displays[i], &profile)))
                printf("ArcSync profile: value=%u name=%s min_Hz=%.6f max_Hz=%.6f increase_us=%u decrease_us=%u\n",
                       (unsigned)profile.IntelArcSyncProfile, profile_name(profile.IntelArcSyncProfile),
                       (double)profile.MinRefreshRateInHz, (double)profile.MaxRefreshRateInHz,
                       (unsigned)profile.MaxFrameTimeIncreaseInUs, (unsigned)profile.MaxFrameTimeDecreaseInUs);
        }
    }
    free(displays);
}

int main(void) {
    puts("IGCL read-only query; no settings changed, no rendering workload.");
    puts("Configured values do not prove that Windows has activated VRR for the current application.");
    wchar_t path[MAX_PATH];
    UINT length = GetSystemDirectoryW(path, MAX_PATH);
    const wchar_t suffix[] = L"\\ControlLib.dll";
    if (!length || length + sizeof suffix / sizeof suffix[0] > MAX_PATH) {
        puts("unsupported: cannot obtain System32 path"); return 2;
    }
    wcscat(path, suffix);
    HMODULE module = LoadLibraryExW(path, NULL, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!module) { printf("unsupported: System32 ControlLib.dll load error=%lu\n", GetLastError()); return 2; }
    ReadApi api = {0};
    LOAD_GETTER(init, "ctlInit");
    LOAD_GETTER(close, "ctlClose");
    LOAD_GETTER(devices, "ctlEnumerateDevices");
    LOAD_GETTER(displays, "ctlEnumerateDisplayOutputs");
    LOAD_GETTER(device_properties, "ctlGetDeviceProperties");
    LOAD_GETTER(display_properties, "ctlGetDisplayProperties");
    LOAD_GETTER(feature_caps, "ctlGetSupported3DCapabilities");
    LOAD_GETTER(get_feature, "ctlGetSet3DFeature");
    LOAD_GETTER(arc_caps, "ctlGetIntelArcSyncInfoForMonitor");
    LOAD_GETTER(arc_profile, "ctlGetIntelArcSyncProfile");
    if (!api.init || !api.close || !api.devices) {
        puts("unsupported: cannot initialize and enumerate safely; optional APIs above may be absent");
        FreeLibrary(module); return 2;
    }
    ctl_init_args_t init = {0};
    init.Size = sizeof init;
    init.Version = 0;
    init.AppVersion = CTL_MAKE_VERSION(1, 0);
    init.flags = 0;
    ctl_api_handle_t handle = NULL;
    if (!result_ok("ctlInit", api.init(&init, &handle))) { FreeLibrary(module); return 2; }
    printf("IGCL SupportedVersion=%u.%u requested=1.0 flags=0 header_commit=cafcc9fc0dcc3594e085c3058a0e830fcafd3de3\n",
           (unsigned)CTL_MAJOR_VERSION(init.SupportedVersion), (unsigned)CTL_MINOR_VERSION(init.SupportedVersion));
    uint32_t count = 0;
    ctl_device_adapter_handle_t* devices = NULL;
    if (result_ok("ctlEnumerateDevices/count", api.devices(handle, &count, NULL)) && count && count <= 64) {
        uint32_t capacity = count;
        devices = calloc(capacity, sizeof *devices);
        if (devices && result_ok("ctlEnumerateDevices/list", api.devices(handle, &count, devices))) {
            if (count > capacity) count = capacity;
            for (uint32_t i = 0; i < count; i++) {
                printf("adapter[%u]\n", (unsigned)i);
                if (api.device_properties) {
                    ctl_device_adapter_properties_t properties = {0};
                    LUID luid = {0};
                    properties.Size = sizeof properties;
                    properties.Version = 0;
                    properties.pDeviceID = &luid;
                    properties.device_id_size = sizeof luid;
                    if (result_ok("ctlGetDeviceProperties", api.device_properties(devices[i], &properties))) {
                        printf("adapter: name=%.*s vendor=0x%X device=0x%X type=%u driver=0x%016llX\n",
                               (int)sizeof properties.name, properties.name, (unsigned)properties.pci_vendor_id,
                               (unsigned)properties.pci_device_id, (unsigned)properties.device_type,
                               (unsigned long long)properties.driver_version);
                        if (properties.device_type != CTL_DEVICE_TYPE_GRAPHICS) continue;
                    }
                }
                int per_app = print_asp_caps(&api, devices[i]);
                char global[] = "";
                char game[] = "01001B300B9BE000.exe";
                print_asp(&api, devices[i], global);
                if (per_app != 0) {
                    if (per_app < 0) puts("ASP per-app support unknown; getter result must be treated accordingly");
                    print_asp(&api, devices[i], game);
                } else puts("ASP per-app query unsupported by advertised capability");
                print_displays(&api, devices[i]);
            }
        }
    } else printf("adapter_count=%u; no adapter queries\n", (unsigned)count);
    free(devices);
    bool closed = result_ok("ctlClose", api.close(handle));
    if (closed) FreeLibrary(module);
    return closed ? 0 : 2;
}
