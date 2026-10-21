/* SPDX-License-Identifier: GPL-3.0-or-later
   Copyright 2026 the ScarletNX contributors */
/* Native Win32/D3D11 clear-and-present probe. Does not change the display mode.
   clang -std=c11 -O2 -Wall -Wextra -Werror tools/windows-dev/dxgi-present-probe.c \
     -o out/windows/dxgi-present-probe.exe -ld3d11 -ldxgi -ldxguid -luser32
   CPU timings and successful Present calls are NOT measured display FPS. */
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#define COBJMACROS
#include <windows.h>
#include <d3d11.h>
#include <dxgi1_3.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef CREATE_WAITABLE_TIMER_HIGH_RESOLUTION
#define CREATE_WAITABLE_TIMER_HIGH_RESOLUTION 0x00000002
#endif

typedef struct { double sum, max; uint64_t over20; } Metric;
static LARGE_INTEGER frequency;
static int closing;
static int64_t tick(void) { LARGE_INTEGER q; QueryPerformanceCounter(&q); return q.QuadPart; }
static double ms(int64_t ticks) { return (double)ticks * 1000.0 / (double)frequency.QuadPart; }
static void add(Metric *m, double value) {
    m->sum += value;
    if (value > m->max) m->max = value;
    m->over20 += value > 20.0;
}
static void metric(const char *name, const Metric *m) {
    printf(" %s_sum_ms=%.3f %s_max_ms=%.3f %s_gt20=%llu", name, m->sum, name, m->max,
           name, (unsigned long long)m->over20);
}
static void summary(uint64_t frames, uint64_t attempts, uint64_t failures, uint64_t skips,
                    uint64_t foreground_lost_frames,
                    double elapsed, const Metric *latency, const Metric *clear,
                    const Metric *present, const Metric *sleep) {
    printf("frames=%llu attempts=%llu api_failures=%llu deadline_skips=%llu foreground_lost_frames=%llu elapsed_s=%.3f host_present_fps=%.3f",
           (unsigned long long)frames, (unsigned long long)attempts,
           (unsigned long long)failures, (unsigned long long)skips,
           (unsigned long long)foreground_lost_frames,
           elapsed, elapsed > 0 ? frames / elapsed : 0);
    metric("latency_wait", latency); metric("clear_cpu", clear);
    metric("present", present); metric("limiter_wait", sleep);
    putchar('\n'); fflush(stdout);
}
static LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    if (message == WM_CLOSE) { closing = 1; DestroyWindow(window); return 0; }
    if (message == WM_DESTROY) { closing = 1; PostQuitMessage(0); return 0; }
    if (message == WM_PAINT) { ValidateRect(window, NULL); return 0; }
    return DefWindowProcW(window, message, wparam, lparam);
}
static void pump(void) {
    MSG message;
    while (PeekMessageW(&message, NULL, 0, 0, PM_REMOVE)) {
        if (message.message == WM_QUIT) closing = 1;
        TranslateMessage(&message); DispatchMessageW(&message);
    }
}
static const char *arg_value(int *i, int argc, char **argv, const char *name) {
    size_t n = strlen(name);
    if (!strncmp(argv[*i], name, n) && argv[*i][n] == '=') return argv[*i] + n + 1;
    if (!strcmp(argv[*i], name) && *i + 1 < argc) return argv[++*i];
    return NULL;
}
static int unsigned_arg(const char *s, unsigned max, unsigned *out) {
    char *end;
    unsigned long value;
    if (!*s || *s == '-') return 0;
    errno = 0; value = strtoul(s, &end, 10);
    if (errno || *end || value > max) return 0;
    *out = (unsigned)value; return 1;
}
static int checked(HRESULT hr, const char *call) {
    if (SUCCEEDED(hr)) return 1;
    fprintf(stderr, "%s failed HRESULT=0x%08lx\n", call, (unsigned long)hr); return 0;
}
#define TRY(call) do { if (!checked((call), #call)) goto cleanup; } while (0)
#define RELEASE(p) do { if (p) { IUnknown_Release((IUnknown *)(p)); (p) = NULL; } } while (0)

/* Pump messages while waiting. Only WAIT_OBJECT_0 authorizes another render.
   Timeouts, abandoned handles and failures must not masquerade as frame readiness. */
static DWORD wait_ready(HANDLE handle, DWORD timeout_ms) {
    int64_t start = tick();
    for (;;) {
        double elapsed = ms(tick() - start);
        if (elapsed >= timeout_ms) return WAIT_TIMEOUT;
        DWORD left = timeout_ms - (DWORD)elapsed;
        DWORD status = MsgWaitForMultipleObjectsEx(1, &handle, left, QS_ALLINPUT, MWMO_INPUTAVAILABLE);
        if (status != WAIT_OBJECT_0 + 1) return status;
        pump();
        if (closing) return WAIT_OBJECT_0 + 1;
    }
}

int main(int argc, char **argv) {
    int result = 1, registered = 0, high_resolution_timer = 1, wait_for_focus = 0, vsync_only = 0;
    unsigned width = 0, height = 0, target_fps = 60, sync_interval = 1, maximum_latency = 1;
    double seconds = 30;
    const char *output = NULL;
    FILE *csv = NULL;
    HWND window = NULL;
    HINSTANCE module = GetModuleHandleW(NULL);
    HANDLE timer = NULL, latency_handle = NULL;
    ID3D11Device *device = NULL;
    ID3D11DeviceContext *context = NULL;
    IDXGIDevice *dxgi_device = NULL;
    IDXGIAdapter *adapter = NULL;
    IDXGIFactory2 *factory = NULL;
    IDXGISwapChain1 *swapchain1 = NULL;
    IDXGISwapChain2 *swapchain = NULL;
    ID3D11Texture2D *backbuffer = NULL;
    ID3D11RenderTargetView *view = NULL;
    D3D_FEATURE_LEVEL feature_level = 0;
    Metric latency_metric = {0}, clear_metric = {0}, present_metric = {0}, sleep_metric = {0};
    uint64_t frames = 0, attempts = 0, failures = 0, deadline_skips = 0, foreground_lost_frames = 0;
    int64_t epoch = 0;

    for (int i = 1; i < argc; ++i) {
        const char *v;
        if (!strcmp(argv[i], "--help")) {
            puts("dxgi-present-probe [--seconds 30] [--fps 60] [--sync 0|1|2] [--latency 1|2] [--width N --height N] [--output PATH] [--wait-for-focus] [--vsync-only]");
            puts("Defaults: sync=1 latency=1. No tearing flag; sync=0 allows flip-queue replacement, not guaranteed immediate scanout.");
            puts("--wait-for-focus observes focus for up to 30 seconds before timing; does not activate the window.");
            puts("--vsync-only requires sync>0 and disables the host timer limiter; --fps then does not control pacing.");
            return 0;
        }
        if (!strcmp(argv[i], "--wait-for-focus")) wait_for_focus = 1;
        else if (!strcmp(argv[i], "--vsync-only")) vsync_only = 1;
        else if ((v = arg_value(&i, argc, argv, "--seconds"))) {
            char *end;
            errno = 0; seconds = strtod(v, &end);
            if (!*v || *end || errno || !(seconds > 0 && seconds <= 3600)) {
                fputs("Invalid duration\n", stderr); return 2;
            }
        } else if ((v = arg_value(&i, argc, argv, "--fps"))) {
            if (!unsigned_arg(v, 240, &target_fps) || target_fps < 10) { fputs("Invalid FPS\n", stderr); return 2; }
        } else if ((v = arg_value(&i, argc, argv, "--sync"))) {
            if (!unsigned_arg(v, 2, &sync_interval)) { fputs("Invalid sync interval (expected 0, 1 or 2)\n", stderr); return 2; }
        } else if ((v = arg_value(&i, argc, argv, "--latency"))) {
            if (!unsigned_arg(v, 2, &maximum_latency) || maximum_latency < 1) { fputs("Invalid maximum latency (expected 1 or 2)\n", stderr); return 2; }
        } else if ((v = arg_value(&i, argc, argv, "--width"))) {
            if (!unsigned_arg(v, 16384, &width)) { fputs("Invalid width\n", stderr); return 2; }
        } else if ((v = arg_value(&i, argc, argv, "--height"))) {
            if (!unsigned_arg(v, 16384, &height)) { fputs("Invalid height\n", stderr); return 2; }
        } else if ((v = arg_value(&i, argc, argv, "--output"))) output = v;
        else { fprintf(stderr, "Unknown/incomplete argument: %s\n", argv[i]); return 2; }
    }
    if (vsync_only && !sync_interval) { fputs("--vsync-only requires a positive sync interval\n", stderr); return 2; }
    if (!QueryPerformanceFrequency(&frequency)) { fputs("QueryPerformanceFrequency failed\n", stderr); goto cleanup; }
    SetProcessDPIAware();
    if (!width) width = (unsigned)GetSystemMetrics(SM_CXSCREEN);
    if (!height) height = (unsigned)GetSystemMetrics(SM_CYSCREEN);
    if (output) {
        csv = fopen(output, "wb");
        if (!csv) { perror(output); goto cleanup; }
        setvbuf(csv, NULL, _IOFBF, 1 << 20);
        fputs("frame,scheduled_qpc,limiter_begin_qpc,frame_start_qpc,clear_qpc,present_qpc,frame_end_qpc,qpc_frequency,limiter_wait_ms,start_late_ms,latency_wait_ms,clear_cpu_ms,present_ms,cpu_frame_ms,latency_wait_result,present_result,deadline_skips_total\n", csv);
    }
    WNDCLASSW wc = {0};
    wc.lpfnWndProc = window_proc; wc.hInstance = module; wc.lpszClassName = L"DiabloDXGIPresentProbe";
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    if (!RegisterClassW(&wc)) { fprintf(stderr, "RegisterClass error=%lu\n", GetLastError()); goto cleanup; }
    registered = 1;
    wchar_t title[96];
    if (vsync_only) swprintf(title, sizeof title / sizeof *title, L"DXGI Present Probe - VSync interval %u clear", sync_interval);
    else swprintf(title, sizeof title / sizeof *title, L"DXGI Present Probe - %u FPS clear", target_fps);
    window = CreateWindowExW(0, wc.lpszClassName, title, WS_POPUP, 0, 0, (int)width, (int)height,
                             NULL, NULL, module, NULL);
    if (!window) { fprintf(stderr, "CreateWindow error=%lu\n", GetLastError()); goto cleanup; }
    ShowWindow(window, SW_SHOW); UpdateWindow(window);

    const D3D_FEATURE_LEVEL levels[] = {D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0};
    TRY(D3D11CreateDevice(NULL, D3D_DRIVER_TYPE_HARDWARE, NULL, D3D11_CREATE_DEVICE_BGRA_SUPPORT,
                         levels, sizeof levels / sizeof *levels, D3D11_SDK_VERSION,
                         &device, &feature_level, &context));
    TRY(ID3D11Device_QueryInterface(device, &IID_IDXGIDevice, (void **)&dxgi_device));
    TRY(IDXGIDevice_GetAdapter(dxgi_device, &adapter));
    DXGI_ADAPTER_DESC adapter_desc;
    TRY(IDXGIAdapter_GetDesc(adapter, &adapter_desc));
    TRY(IDXGIAdapter_GetParent(adapter, &IID_IDXGIFactory2, (void **)&factory));
    TRY(IDXGIFactory2_MakeWindowAssociation(factory, window, DXGI_MWA_NO_ALT_ENTER));
    DXGI_SWAP_CHAIN_DESC1 desc = {0};
    desc.Width = width; desc.Height = height; desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    desc.SampleDesc.Count = 1; desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    desc.BufferCount = 2; desc.Scaling = DXGI_SCALING_STRETCH;
    desc.SwapEffect = DXGI_SWAP_EFFECT_FLIP_DISCARD; desc.AlphaMode = DXGI_ALPHA_MODE_IGNORE;
    desc.Flags = DXGI_SWAP_CHAIN_FLAG_FRAME_LATENCY_WAITABLE_OBJECT;
    TRY(IDXGIFactory2_CreateSwapChainForHwnd(factory, (IUnknown *)device, window, &desc, NULL, NULL, &swapchain1));
    TRY(IDXGISwapChain1_QueryInterface(swapchain1, &IID_IDXGISwapChain2, (void **)&swapchain));
    TRY(IDXGISwapChain2_SetMaximumFrameLatency(swapchain, maximum_latency));
    latency_handle = IDXGISwapChain2_GetFrameLatencyWaitableObject(swapchain);
    if (!latency_handle) { fputs("No frame latency waitable object\n", stderr); goto cleanup; }
    TRY(IDXGISwapChain2_GetBuffer(swapchain, 0, &IID_ID3D11Texture2D, (void **)&backbuffer));
    TRY(ID3D11Device_CreateRenderTargetView(device, (ID3D11Resource *)backbuffer, NULL, &view));
    if (!vsync_only) {
        timer = CreateWaitableTimerExW(NULL, NULL, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS);
        if (!timer) { high_resolution_timer = 0; timer = CreateWaitableTimerExW(NULL, NULL, 0, TIMER_ALL_ACCESS); }
        if (!timer) { fprintf(stderr, "CreateWaitableTimer error=%lu\n", GetLastError()); goto cleanup; }
    } else high_resolution_timer = 0;
    char adapter_name[256] = {0};
    if (!WideCharToMultiByte(CP_UTF8, 0, adapter_desc.Description, -1, adapter_name,
                             sizeof adapter_name, NULL, NULL)) strcpy(adapter_name, "(name unavailable)");
    printf("hwnd=%llu wait_for_focus=%d focus_timeout_s=30\n", (unsigned long long)(uintptr_t)window, wait_for_focus);
    fflush(stdout);
    if (wait_for_focus) {
        int64_t wait_begin = tick();
        for (;;) {
            pump();
            if (closing) { result = 0; goto cleanup; }
            if (GetForegroundWindow() == window) break;
            if (ms(tick() - wait_begin) >= 30000) {
                fputs("Foreground wait timed out; no timing samples collected\n", stderr); goto cleanup;
            }
            Sleep(10);
        }
    }
    int foreground_at_start = GetForegroundWindow() == window;
    printf("gpu=%s vendor=0x%04x device=0x%04x feature_level=0x%x extent=%ux%u buffers=2 mode=FLIP_DISCARD sync_interval=%u max_latency=%u tearing=0 target_fps=%u host_limiter=%s high_resolution_timer=%d qpc_frequency=%lld seconds=%.3f focus_tracking=%d foreground_at_start=%d\n",
           adapter_name, adapter_desc.VendorId, adapter_desc.DeviceId, (unsigned)feature_level,
           width, height, sync_interval, maximum_latency, target_fps, vsync_only ? "off" : "on", high_resolution_timer,
           (long long)frequency.QuadPart, seconds, wait_for_focus, foreground_at_start);
    fflush(stdout);

    epoch = tick(); uint64_t schedule_tick = 0;
    result = 0;
    while (!closing) {
        pump();
        if (closing || ms(tick() - epoch) >= seconds * 1000) break;
        int64_t sleep_begin = tick();
        int64_t scheduled = vsync_only ? sleep_begin : epoch + (int64_t)(schedule_tick * (uint64_t)frequency.QuadPart / target_fps);
        if (!vsync_only && scheduled > sleep_begin) {
            LARGE_INTEGER due; due.QuadPart = -(scheduled - sleep_begin) * 10000000 / frequency.QuadPart;
            if (!due.QuadPart) due.QuadPart = -1;
            if (!SetWaitableTimer(timer, &due, 0, NULL, NULL, FALSE) ||
                WaitForSingleObject(timer, 2000) != WAIT_OBJECT_0) {
                fprintf(stderr, "Limiter wait failed error=%lu\n", GetLastError()); result = 1; break;
            }
        }
        int64_t frame_start = tick(), clear_qpc = 0, present_qpc = 0;
        if (wait_for_focus && GetForegroundWindow() != window) ++foreground_lost_frames;
        double sleep_ms = ms(frame_start - sleep_begin), clear_ms = 0, present_ms = 0;
        add(&sleep_metric, sleep_ms);
        DWORD wait_status = wait_ready(latency_handle, 2000);
        int64_t ready_qpc = tick();
        double latency_ms = ms(ready_qpc - frame_start);
        add(&latency_metric, latency_ms);
        if (closing) break;
        HRESULT present_result = E_PENDING;
        if (wait_status == WAIT_OBJECT_0) {
            float phase = (float)(frames % 600) / 600.0f;
            const float color[4] = {0.08f + 0.25f * phase, 0.12f, 0.35f - 0.25f * phase, 1};
            clear_qpc = tick();
            ID3D11DeviceContext_ClearRenderTargetView(context, view, color);
            clear_ms = ms(tick() - clear_qpc); add(&clear_metric, clear_ms);
            present_qpc = tick();
            /* For flip model, interval zero cancels the remaining display time of the
               previous frame and may discard queued frames. Without ALLOW_TEARING,
               it is not a request to scan out mid-refresh. Measure actual display events. */
            present_result = IDXGISwapChain2_Present(swapchain, sync_interval, 0);
            present_ms = ms(tick() - present_qpc); add(&present_metric, present_ms);
        }
        int64_t end = tick();
        ++attempts;
        if (!vsync_only) {
            ++schedule_tick;
            uint64_t next_tick = (uint64_t)(end - epoch) * target_fps / (uint64_t)frequency.QuadPart + 1;
            if (next_tick > schedule_tick) { deadline_skips += next_tick - schedule_tick; schedule_tick = next_tick; }
        }
        if (csv) fprintf(csv, "%llu,%lld,%lld,%lld,%lld,%lld,%lld,%lld,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%lu,0x%08lx,%llu\n",
            (unsigned long long)attempts, (long long)scheduled, (long long)sleep_begin, (long long)frame_start,
            (long long)clear_qpc, (long long)present_qpc, (long long)end, (long long)frequency.QuadPart,
            sleep_ms, ms(frame_start - scheduled), latency_ms, clear_ms, present_ms, ms(end - frame_start),
            (unsigned long)wait_status, (unsigned long)present_result, (unsigned long long)deadline_skips);
        if (wait_status != WAIT_OBJECT_0 || present_result != S_OK) {
            ++failures; result = 1;
            fprintf(stderr, "Frame failure: latency_wait=%lu present=0x%08lx device_removed=0x%08lx\n",
                    (unsigned long)wait_status, (unsigned long)present_result,
                    (unsigned long)ID3D11Device_GetDeviceRemovedReason(device));
            break;
        }
        ++frames;
        if (frames % 600 == 0) summary(frames, attempts, failures, deadline_skips, foreground_lost_frames,
            ms(end - epoch) / 1000, &latency_metric, &clear_metric, &present_metric, &sleep_metric);
    }
    summary(frames, attempts, failures, deadline_skips, foreground_lost_frames, ms(tick() - epoch) / 1000,
            &latency_metric, &clear_metric, &present_metric, &sleep_metric);
cleanup:
    if (context) { ID3D11DeviceContext_ClearState(context); ID3D11DeviceContext_Flush(context); }
    if (latency_handle) CloseHandle(latency_handle);
    RELEASE(view); RELEASE(backbuffer); RELEASE(swapchain); RELEASE(swapchain1);
    RELEASE(factory); RELEASE(adapter); RELEASE(dxgi_device); RELEASE(context); RELEASE(device);
    if (timer) CloseHandle(timer);
    if (window && IsWindow(window)) DestroyWindow(window);
    if (registered) UnregisterClassW(L"DiabloDXGIPresentProbe", module);
    if (csv && fclose(csv)) { perror("CSV close"); result = 1; }
    return result;
}
