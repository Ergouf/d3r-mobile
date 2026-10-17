<#
  Build the Eden GPU subtree (video_core, Vulkan scope) into libeden_gpu.a and
  report unresolved-symbol counts.  M0 acceptance: the archive builds and its
  object files only reference the host interface we implement.

  Usage:
    pwsh -File build_gpu.ps1            # incremental compile + archive
    pwsh -File build_gpu.ps1 -Clean
#>
param(
    [switch]$Clean,
    [int]$Throttle = 8,
    [string]$Opt = '-O1'
)

$ErrorActionPreference = 'Stop'

$Root    = 'D:\workspace\Diablo'
$Shim    = Join-Path $Root 'd3-android\gpu\shim'
$Third   = Join-Path $Root 'd3-android\gpu\third_party'
$Gen     = Join-Path $Root 'd3-android\gpu\gen\include'
$Eden    = Join-Path $Root 'reference\eden'
$EdenSrc = Join-Path $Eden 'src'
$ObjRoot = Join-Path $Root 'd3-android\build\gpu-obj'
$Lib     = Join-Path $Root 'd3-android\build\libeden_gpu.a'
$Bin     = 'D:\workspace\Gdict\android_sdk\ndk\28.2.13676358\toolchains\llvm\prebuilt\windows-x86_64\bin'
$Clang   = Join-Path $Bin 'clang++.exe'
$Ar      = Join-Path $Bin 'llvm-ar.exe'

if ($Clean) {
    Remove-Item -Recurse -Force $ObjRoot -ErrorAction SilentlyContinue
    Remove-Item -Force $Lib -ErrorAction SilentlyContinue
}

# Directories that cannot contribute to the first Vulkan frame.
$exclude = @(
    '\\renderer_opengl\\',
    '\\host1x\\codecs\\',
    '\\host1x\\ffmpeg\.cpp$',
    '\\host1x\\vic\.cpp$',
    '\\post_processing\\',
    '\\present\\post_process\.cpp$'
)

$files = Get-ChildItem -Path (Join-Path $EdenSrc 'video_core') -Recurse -Filter *.cpp -File |
         Where-Object { $p = $_.FullName; -not ($exclude | Where-Object { $p -match $_ }) } |
         ForEach-Object { $_.FullName }

# Eden components the GPU path calls into directly, plus our host adapter.
$files += @(
    (Join-Path $EdenSrc 'common\assert.cpp'),
    (Join-Path $EdenSrc 'common\cityhash.cpp'),
    (Join-Path $EdenSrc 'common\dynamic_library.cpp'),
    (Join-Path $EdenSrc 'common\address_space.cpp'),
    (Join-Path $EdenSrc 'common\page_table.cpp'),
    (Join-Path $EdenSrc 'common\multi_level_page_table.cpp'),
    (Join-Path $EdenSrc 'common\fs\file.cpp'),
    (Join-Path $EdenSrc 'common\fs\fs_util.cpp'),
    (Join-Path $EdenSrc 'common\fs\fs.cpp'),
    (Join-Path $EdenSrc 'common\host_memory.cpp'),
    (Join-Path $EdenSrc 'common\settings.cpp'),
    (Join-Path $EdenSrc 'common\settings_common.cpp'),
    (Join-Path $EdenSrc 'common\thread.cpp'),
    (Join-Path $EdenSrc 'common\adpf.cpp'),
    (Join-Path $EdenSrc 'common\error.cpp'),
    (Join-Path $EdenSrc 'common\logging.cpp'),
    (Join-Path $EdenSrc 'common\time_zone.cpp'),
    (Join-Path $EdenSrc 'core\frontend\emu_window.cpp'),
    (Join-Path $EdenSrc 'core\frontend\framebuffer_layout.cpp'),
    (Join-Path $Eden 'externals\bc_decoder\bc_decoder.cpp'),
    (Join-Path $Eden 'externals\stb\stb_dxt.cpp')
)
$files += Get-ChildItem -Path (Join-Path $EdenSrc 'shader_recompiler') -Recurse -Filter *.cpp -File |
          ForEach-Object { $_.FullName }
# SPIR-V builder used by shader_recompiler's backend.
$files += Get-ChildItem -Path (Join-Path $Third 'sirit\src') -Recurse -Filter *.cpp -File |
          ForEach-Object { $_.FullName }
$files += (Join-Path $EdenSrc 'common\fs\fs_android.cpp')
$files += (Join-Path $EdenSrc 'common\fs\path_util.cpp')
$files += (Join-Path $EdenSrc 'common\android\android_common.cpp')
$files += (Join-Path $EdenSrc 'common\android\id_cache.cpp')
$files += (Join-Path $EdenSrc 'common\string_util.cpp')
$files += Get-ChildItem -Path (Join-Path $Root 'd3-android\gpu\host') -Filter *.cpp -File |
          ForEach-Object { $_.FullName }

$common = @(
    '--target=aarch64-linux-android34', '-std=c++20', '-c', $Opt,
    '-D_LIBCPP_ENABLE_EXPERIMENTAL=1', '-DFMT_HEADER_ONLY', '-fPIC', '-fvisibility=hidden',
    '-I', $Shim,
    '-I', (Join-Path $Third 'Vulkan-Headers\include'),
    '-I', (Join-Path $Third 'Vulkan-Utility-Libraries\include'),
    '-I', (Join-Path $Third 'VMA\include'),
    '-I', $Gen,
    '-I', (Join-Path $Third 'fmt\include'),
    '-I', (Join-Path $Third 'boost\boost_1_86_0'),
    '-I', (Join-Path $Third 'sirit\include'),
    '-I', (Join-Path $Third 'sirit\src'),
    '-I', (Join-Path $Third 'sirit\src\instructions'),
    '-I', (Join-Path $Third 'SPIRV-Headers\include'),
    '-I', (Join-Path $Eden 'externals\stb'),
    '-I', (Join-Path $Eden 'externals\bc_decoder'),
    '-I', $EdenSrc,
    '-Wno-ignored-attributes'
)

Write-Host "objects: $($files.Count) translation units"

$results = $files | ForEach-Object -Parallel {
    $cc  = $using:Clang
    $src = $_
    $rel = ($src.Substring(3) -replace '[\\/:]', '__') -replace '\.cpp$', '.o'
    $obj = Join-Path $using:ObjRoot $rel
    New-Item -ItemType Directory -Force -Path (Split-Path $obj) | Out-Null
    if ((Test-Path $obj) -and (Get-Item $obj).LastWriteTime -gt (Get-Item $src).LastWriteTime) {
        [pscustomobject]@{ Src = $src; Obj = $obj; Ok = $true; Cached = $true; Err = '' }
        return
    }
    $out = @(& $cc @using:common $src -o $obj 2>&1 | ForEach-Object { "$_" })
    [pscustomobject]@{
        Src = $src; Obj = $obj; Ok = ($LASTEXITCODE -eq 0); Cached = $false
        Err = ($out | Where-Object { $_ -match 'error:' } | Select-Object -First 1)
    }
} -ThrottleLimit $Throttle

$failed = @($results | Where-Object { -not $_.Ok })
$built  = @($results | Where-Object { $_.Ok })
Write-Host ("compiled {0}/{1} (cached {2})" -f $built.Count, $results.Count, @($built | Where-Object Cached).Count)
if ($failed.Count) {
    $failed | Select-Object -First 15 Src, Err | Format-Table -AutoSize -Wrap
    throw "$($failed.Count) translation units failed"
}

$objs = $built | ForEach-Object { $_.Obj }
# 300+ object paths overflow the Windows command line, so hand llvm-ar a
# response file instead.
$rsp = Join-Path $ObjRoot 'archive.rsp'
Remove-Item -Force $Lib -ErrorAction SilentlyContinue
Set-Content -Path $rsp -Value ($objs | ForEach-Object { '"' + $_ + '"' }) -Encoding ASCII
& $Ar rcs $Lib "@$rsp"
if ($LASTEXITCODE -ne 0) { throw "llvm-ar failed" }

Write-Host ""
Write-Host ("archive: {0} ({1:N1} MB)" -f $Lib, ((Get-Item $Lib).Length / 1MB))
Write-Host ""
Write-Host "== undefined symbols (grouped by namespace prefix) =="
$nm = Join-Path $Bin 'llvm-nm.exe'
& $nm -u --demangle $Lib 2>$null |
    ForEach-Object { ($_ -replace '^\s+U\s+', '').Trim() } |
    Where-Object { $_ } |
    ForEach-Object {
        if ($_ -match '^(Core|Tegra|VideoCore|Common|Settings|Shader|FFmpeg|Vulkan)::') { $Matches[1] + '::' } else { 'extern "C" / std' }
    } |
    Group-Object | Sort-Object Count -Descending | Select-Object Count, Name | Format-Table -AutoSize
