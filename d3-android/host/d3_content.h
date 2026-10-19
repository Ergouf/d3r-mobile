#pragma once

#include "d3_host.h"
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#ifndef D3_CONTENT_ROOT
#define D3_CONTENT_ROOT "/data/local/tmp/d3romfs"
#endif

/* A staged directory is visible only after its import completed. The marker
   contains the actual DLC title ID; an empty/partial directory is not installed. */
static inline int d3_content_addon_root(unsigned index, char *out, size_t capacity) {
    if (index > 0xfff) return 0;
    const int count = snprintf(out, capacity, D3_CONTENT_ROOT "/AddOnContent/%u", index);
    if (count < 0 || (size_t)count >= capacity) return 0;
    char marker[640];
    snprintf(marker, sizeof marker, "%s/.d3-content-complete", out);
    FILE *file = fopen(marker, "re");
    if (!file) return 0;
    unsigned long long title = 0;
    const int valid = fscanf(file, "%llx", &title) == 1 && title == (0x01001b300b9bf000ull | index);
    fclose(file);
    return valid;
}

static inline size_t d3_content_addon_ids(unsigned *ids, size_t capacity) {
    DIR *directory = opendir(D3_CONTENT_ROOT "/AddOnContent");
    if (!directory) return 0;
    struct dirent *entry;
    size_t count = 0;
    while ((entry = readdir(directory))) {
        if (entry->d_name[0] < '0' || entry->d_name[0] > '9') continue;
        char *end;
        const unsigned long value = strtoul(entry->d_name, &end, 10);
        if (*end || value > 0xfff || count == capacity) continue;
        char root[512];
        if (!d3_content_addon_root((unsigned)value, root, sizeof root)) continue;
        size_t position = count;
        while (position && ids[position - 1] > value) {
            ids[position] = ids[position - 1]; --position;
        }
        ids[position] = (unsigned)value;
        ++count;
    }
    closedir(directory);
    return count;
}
