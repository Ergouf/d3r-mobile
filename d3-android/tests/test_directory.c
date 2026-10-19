#include "../host/d3_host.c"

#define CHECK(condition) do { if (!(condition)) { \
    fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); return 1; \
} } while (0)

int main(void) {
    char root[] = "/data/local/tmp/d3romfs/d3-directory-XXXXXX";
    CHECK(mkdtemp(root) != NULL);
    const int parent = open(root, O_RDONLY | O_DIRECTORY);
    CHECK(parent >= 0);
    const int file = openat(parent, "Patch.cpk", O_CREAT | O_EXCL | O_WRONLY, 0600);
    CHECK(file >= 0 && write(file, "CPK", 3) == 3 && close(file) == 0);
    CHECK(mkdirat(parent, "child", 0700) == 0);
    CHECK(symlinkat("Patch.cpk", parent, "link") == 0);
    char path[256];
    snprintf(path, sizeof path, "data:/%s", strrchr(root, '/') + 1);
    uint64_t handle = 0;
    int64_t count = -1;
    CHECK(hook_fs_open_directory((uint64_t)(uintptr_t)&handle,
                                 (uint64_t)(uintptr_t)path, 3) == 0);
    CHECK(hook_fs_directory_count((uint64_t)(uintptr_t)&count, handle) == 0 && count == 2);
    GuestDirectoryEntry entry;
    int files = 0, directories = 0;
    for (int index = 0; index < 2; index++) {
        CHECK(hook_fs_read_directory((uint64_t)(uintptr_t)&count,
                                      (uint64_t)(uintptr_t)&entry, handle, 1) == 0 && count == 1);
        if (strcmp(entry.name, "Patch.cpk") == 0) {
            CHECK(entry.type == 1 && entry.size == 3);
            files++;
        } else {
            CHECK(strcmp(entry.name, "child") == 0 && entry.type == 0 && entry.size == 0);
            directories++;
        }
        CHECK(hook_fs_directory_count((uint64_t)(uintptr_t)&count, handle) == 0 && count == 2);
    }
    CHECK(files == 1 && directories == 1);
    CHECK(hook_fs_read_directory((uint64_t)(uintptr_t)&count,
                                  (uint64_t)(uintptr_t)&entry, handle, 1) == 0 && count == 0);
    CHECK(hook_fs_close_directory(handle) == 0);
    CHECK(hook_fs_directory_count((uint64_t)(uintptr_t)&count, handle) != 0);
    CHECK(hook_fs_open_directory((uint64_t)(uintptr_t)&handle,
                                 (uint64_t)(uintptr_t)path, 2) == 0);
    CHECK(hook_fs_directory_count((uint64_t)(uintptr_t)&count, handle) == 0 && count == 1);
    CHECK(hook_fs_close_directory(handle) == 0);
    CHECK(hook_fs_open_directory((uint64_t)(uintptr_t)&handle,
                                 (uint64_t)(uintptr_t)path, 0) != 0);
    char file_path[280];
    snprintf(file_path, sizeof file_path, "%s/Patch.cpk", path);
    uint64_t handles[48] = {0};
    for (size_t index = 0; index < 48; index++) {
        CHECK(hook_fs_open_file((uint64_t)(uintptr_t)&handles[index],
                                (uint64_t)(uintptr_t)file_path, 1) == 0);
        for (size_t previous = 0; previous < index; previous++)
            CHECK(handles[previous] != handles[index]);
    }
    for (size_t index = 0; index < 48; index++)
        CHECK(hook_fs_close_file(handles[index]) == 0);
    CHECK(unlinkat(parent, "link", 0) == 0);
    CHECK(unlinkat(parent, "Patch.cpk", 0) == 0);
    CHECK(unlinkat(parent, "child", AT_REMOVEDIR) == 0);
    CHECK(close(parent) == 0 && rmdir(root) == 0);
    puts("PASS: Horizon directory ABI, entry filters, size, count cursor, close and symlink exclusion");
    return 0;
}
