/* Standalone Android loader/boot probe. It never installs or replaces an APK. */
#include <dlfcn.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static void deadline(int signal_number) {
    (void)signal_number;
    static const char message[] = "probe: deadline reached; guest completion not established\n";
    (void)write(STDERR_FILENO, message, sizeof message - 1);
    _exit(124);
}

int main(int argc, char **argv) {
    setvbuf(stdout, NULL, _IONBF, 0);
    if (argc < 3 || (argv[1][0] != 'l' && argv[1][0] != 'b')) {
        fprintf(stderr, "usage: %s load HOST.so | boot HOST.so GUEST.so [seconds]\n", argv[0]);
        return 2;
    }
    const int boot = argv[1][0] == 'b';
    if (boot && (argc < 4 || argc > 5))
        return 2;
    unsigned seconds = 15;
    if (argc == 5) {
        char *end = NULL;
        unsigned long value = strtoul(argv[4], &end, 10);
        if (!end || *end || value < 1 || value > 120)
            return 2;
        seconds = (unsigned)value;
    }
    printf("probe: pid=%ld host=%s\n", (long)getpid(), argv[2]);
    void *library = dlopen(argv[2], RTLD_NOW | RTLD_LOCAL);
    if (!library) {
        fprintf(stderr, "probe: dlopen failed: %s\n", dlerror());
        return 3;
    }
    dlerror();
    int (*start)(const char *) = (int (*)(const char *))dlsym(library, "d3_host_start");
    const char *error = dlerror();
    if (error || !start) {
        fprintf(stderr, "probe: d3_host_start missing: %s\n", error ? error : "null symbol");
        dlclose(library);
        return 4;
    }
    puts("probe: RTLD_NOW and d3_host_start lookup passed");
    if (!boot) {
        dlclose(library);
        return 0;
    }
    struct sigaction action = {0};
    action.sa_handler = deadline;
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGALRM, &action, NULL) != 0)
        return 5;
    alarm(seconds);
    printf("probe: starting guest=%s deadline=%u seconds\n", argv[3], seconds);
    int result = start(argv[3]);
    printf("probe: d3_host_start returned %d (detached guest may still be running)\n", result);
    if (result != 0)
        return 6;
    /* The recovered API starts a detached thread. Stay alive for its diagnostics. */
    for (;;)
        pause();
}
