/* Read-only clock calibration for logcat timestamps, including time spent suspended. */
#include <inttypes.h>
#include <stdio.h>
#include <time.h>

int main(void) {
    struct timespec monotonic, boottime, realtime;
    if (clock_gettime(CLOCK_MONOTONIC, &monotonic) != 0 ||
        clock_gettime(CLOCK_BOOTTIME, &boottime) != 0 ||
        clock_gettime(CLOCK_REALTIME, &realtime) != 0) {
        perror("clock_gettime");
        return 1;
    }
    printf("{\"monotonic_s\":%jd.%09ld,\"boottime_s\":%jd.%09ld,"
           "\"realtime_s\":%jd.%09ld}\n",
           (intmax_t)monotonic.tv_sec, monotonic.tv_nsec,
           (intmax_t)boottime.tv_sec, boottime.tv_nsec,
           (intmax_t)realtime.tv_sec, realtime.tv_nsec);
    return 0;
}
