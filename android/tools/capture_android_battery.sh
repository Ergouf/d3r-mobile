#!/system/bin/sh
# Runs on the device so removing USB does not interrupt the measurement.
set -u
directory=$1
package=$2
expected_pid=$3
sample_count=$4
interval=$5
max_temperature=${6:-390}
umask 077
mkdir -p "$directory" || exit 1
echo running > "$directory/status"
logcat --pid="$expected_pid" -v monotonic -T 1 -s d3gpu:I D3Host:I D3Recovery:I d3input:I '*:S' \
    > "$directory/logcat.txt" 2> "$directory/logcat.stderr.txt" &
log_pid=$!
cleanup() {
    /data/local/tmp/d3-android-clock > "$directory/clock-end.json"
    kill "$log_pid" 2>/dev/null || true
    wait "$log_pid" 2>/dev/null || true
    am force-stop "$package" >/dev/null 2>&1 || true
}
trap cleanup EXIT
/data/local/tmp/d3-android-clock > "$directory/clock-start.json"
index=0
while [ "$index" -lt "$sample_count" ]; do
    actual_pid=$(pidof "$package")
    if [ "$actual_pid" != "$expected_pid" ]; then
        echo identity_changed > "$directory/status"
        exit 2
    fi
    # Keep run-as output on a pipe: the app domain cannot write shell-owned files.
    proc_state=$(run-as "$package" cat "/proc/$expected_pid/stat")
    if [ -z "$proc_state" ]; then
        echo identity_unavailable > "$directory/status"
        exit 3
    fi
    battery_state=$(dumpsys battery)
    {
        echo '@@SAMPLE'
        /data/local/tmp/d3-android-clock
        echo '@@BATTERY'
        echo "$battery_state"
        echo '@@CURRENT'
        service call batteryproperties 1 i32 2
        echo '@@PROC'
        echo "$proc_state"
        echo '@@END'
    } >> "$directory/samples.raw"
    temperature=$(echo "$battery_state" | sed -n 's/^[[:space:]]*temperature: *\([0-9][0-9]*\).*/\1/p')
    if [ -z "$temperature" ] || [ "$temperature" -ge "$max_temperature" ]; then
        echo temperature_limit > "$directory/status"
        exit 4
    fi
    if [ -f "$directory/stop" ]; then break; fi
    index=$((index + 1))
    if [ "$index" -lt "$sample_count" ]; then sleep "$interval"; fi
done
/data/local/tmp/d3-android-clock > "$directory/clock-end.json"
cleanup
trap - EXIT
echo complete > "$directory/status"
