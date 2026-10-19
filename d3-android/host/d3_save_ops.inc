/* Descriptor-relative save operations. Each path component stays below root. */
static uint32_t save_errno(void) {
    return errno == ENOENT ? D3_RESULT(2, 1) : errno == EEXIST ? D3_RESULT(2, 2) : D3_RESULT(2, 6069);
}

static int save_parent(int root, const char *path, char leaf[0x301]) {
    if (!path || strlen(path) > 0x300) return -1;
    char copy[0x301]; strcpy(copy, path);
    char *cursor = copy;
    while (*cursor == '/') cursor++;
    int parent = dup(root);
    if (parent < 0) return -1;
    for (;;) {
        char *slash = strchr(cursor, '/');
        if (slash) *slash = 0;
        if (strchr(cursor, '\\') || strchr(cursor, ':') || !strcmp(cursor, "..") || !strcmp(cursor, ".")) {
            close(parent); errno = EINVAL; return -1;
        }
        if (!slash) {
            strcpy(leaf, *cursor ? cursor : ".");
            return parent;
        }
        if (*cursor) {
            int next = openat(parent, cursor, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
            close(parent); parent = next;
            if (parent < 0) return -1;
        }
        cursor = slash + 1;
    }
}

static int save_request_path(const Message *m, unsigned index, char path[0x301]) {
    uint64_t address; size_t size;
    return message_io_buffer(m, 0, index, &address, &size) && size && size <= 0x301 &&
        guest_read(path, address, size) && memchr(path, 0, size) != NULL;
}

static uint32_t save_mutate(Message *m, int root, uint32_t command) {
    char path[0x301], leaf[0x301];
    if (!save_request_path(m, 0, path)) return D3_RESULT(2, 1);
    int parent = save_parent(root, path, leaf);
    if (parent < 0) return save_errno();
    int status = -1;
    if (command == 2) status = mkdirat(parent, leaf, 0700);
    else if (command == 1) status = unlinkat(parent, leaf, 0);
    else if (command == 3) status = unlinkat(parent, leaf, AT_REMOVEDIR);
    else if (command == 0) {
        /* CreateFile raw arguments: u32 option, padding, s64 size. */
        uint64_t bytes = 0;
        if (message_arguments(m, 16)) memcpy(&bytes, &m->w[m->magic + 6], 8);
        if (bytes <= INT64_MAX) {
            int file = openat(parent, leaf, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
            if (file >= 0) { status = ftruncate(file, (off_t)bytes); close(file); }
        }
    } else if (command == 5 || command == 6) {
        char target[0x301], target_leaf[0x301];
        if (save_request_path(m, 1, target)) {
            int target_parent = save_parent(root, target, target_leaf);
            if (target_parent >= 0) {
                status = renameat(parent, leaf, target_parent, target_leaf);
                close(target_parent);
            }
        }
    }
    uint32_t result = status == 0 ? 0 : save_errno();
    slog("save command=%u path=%s result=%#x", command, path, result);
    close(parent);
    return result;
}
