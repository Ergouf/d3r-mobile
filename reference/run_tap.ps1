
$ErrorActionPreference='SilentlyContinue'
& 'D:\workspace\Gdict\android_sdk\platform-tools\adb.exe' logcat -c
& 'D:\workspace\Gdict\android_sdk\platform-tools\adb.exe' shell am force-stop com.d3mobile.host.recovery
& 'D:\workspace\Gdict\android_sdk\platform-tools\adb.exe' shell run-as com.d3mobile.host.recovery rm -f files/d3-crash.txt
& 'D:\workspace\Gdict\android_sdk\platform-tools\adb.exe' shell input keyevent KEYCODE_WAKEUP | Out-Null
& 'D:\workspace\Gdict\android_sdk\platform-tools\adb.exe' shell am start -n com.d3mobile.host.recovery/com.d3mobile.host.MainActivity | Out-Null
Start-Sleep -Seconds 3
& 'D:\workspace\Gdict\android_sdk\platform-tools\adb.exe' shell input tap 1280 235
Start-Sleep -Seconds 12
Write-Output ('alive: ' + (& 'D:\workspace\Gdict\android_sdk\platform-tools\adb.exe' shell pidof com.d3mobile.host.recovery))
& 'D:\workspace\Gdict\android_sdk\platform-tools\adb.exe' shell run-as com.d3mobile.host.recovery ls -l files/d3-crash.txt
& 'D:\workspace\Gdict\android_sdk\platform-tools\adb.exe' shell run-as com.d3mobile.host.recovery head -c 500 files/d3-crash.txt
