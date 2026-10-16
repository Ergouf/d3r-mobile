#define _GNU_SOURCE

#include "d3_service.h"
#include "d3_service_names.h"

#include <android/log.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#define LOG_TAG "D3Host"
#define LOG_DIR D3_DATA_ROOT "/logs"
#define LOG_PATH LOG_DIR "/d3-service.log"

/* The CMIF magic the guest writes into a request and expects in a reply. */
#define CMIF_IN 0x49434653u
#define CMIF_OUT 0x4F434653u
#define MESSAGE_BYTES 0x100
#define MESSAGE_WORDS (MESSAGE_BYTES / 4)

/* Horizon result encoding: module in bits 0..8, description in bits 9..21.
   nn::Result treats any non zero value as a failure (nnResultIsFailure). */
#define D3_RESULT(module, description) (((module) & 0x1FFu) | ((description) << 9))

enum { PORT_NONE = 0, PORT_SM, PORT_FSP, PORT_LM, PORT_LOGGER, PORT_OFFLINE, PORT_UNKNOWN };

#define HANDLE_SLOTS 0x400
#define NAME_CHARS 24

/* ------------------------------------------------------------------ logging */

static int g_log = -1;
static int g_log_tried;
static uint32_t g_loud;
static uint32_t g_replies;
static uint32_t g_quiet;
static uint32_t g_last_result;
static uint64_t g_last_signature;
static uint32_t g_last_repeats;

/* Keep the device log from growing without limit: a long run appends a lot. */
#define LOG_MAX_BYTES (64u * 1024u * 1024u)

static int open_log(void) {
    struct stat info;
    if (stat(LOG_PATH, &info) == 0 && (uint64_t)info.st_size > LOG_MAX_BYTES) {
        char old[128];
        snprintf(old, sizeof old, "%s.old", LOG_PATH);
        (void)unlink(old);
        (void)rename(LOG_PATH, old);
    }
    return open(LOG_PATH, O_WRONLY | O_CREAT | O_APPEND, 0666);
}

static void slog(const char *format, ...) {
    char line[1024];
    va_list args;
    va_start(args, format);
    int len = vsnprintf(line, sizeof line, format, args);
    va_end(args);
    if (len < 0)
        return;
    __android_log_print(ANDROID_LOG_INFO, LOG_TAG, "svc %s", line);
    if (g_log_tried == 0) {
        g_log_tried = 1;
        (void)mkdir(D3_DATA_ROOT, 0777);
        (void)mkdir(LOG_DIR, 0777);
        g_log = open_log();
    }
    if (g_log >= 0) {
        char out[1040];
        int n = snprintf(out, sizeof out, "%s\n", line);
        if (n > 0)
            (void)write(g_log, out, (size_t)n < sizeof out ? (size_t)n : sizeof out - 1);
    }
}

static void hexdump_log(const char *what, uint64_t address, const uint8_t *bytes, size_t size) {
    char line[256];
    for (size_t base = 0; base < size; base += 32) {
        int pos = snprintf(line, sizeof line, "%s %#" PRIx64 " +%#zx:", what, address, base);
        for (size_t i = 0; i < 32 && base + i < size; i++)
            pos += snprintf(line + pos, sizeof line - (size_t)pos, " %02x", bytes[base + i]);
        slog("%s", line);
    }
}

void d3_service_dump(const char *what, uint64_t address, const void *data, size_t size) {
    hexdump_log(what, address, (const uint8_t *)data, size);
}

/* ------------------------------------------------------------------ handles */

typedef struct {
    int kind;
    uint64_t arg;
    char name[NAME_CHARS];
} Object;

static Object g_obj[HANDLE_SLOTS];

static Object *object_of(uint32_t handle) {
    if (handle == D3_HANDLE_CURRENT_PROCESS) {
        static Object process;
        process.kind = D3_OBJ_PROCESS;
        process.arg = 1;
        snprintf(process.name, NAME_CHARS, "process");
        return &process;
    }
    if (handle == D3_HANDLE_CURRENT_THREAD) {
        static Object thread;
        thread.kind = D3_OBJ_THREAD;
        thread.arg = 1;
        snprintf(thread.name, NAME_CHARS, "thread");
        return &thread;
    }
    if (handle < D3_HANDLE_FIRST)
        return 0;
    uint32_t index = handle - D3_HANDLE_FIRST;
    if (index >= HANDLE_SLOTS || g_obj[index].kind == D3_OBJ_NONE)
        return 0;
    return &g_obj[index];
}

uint32_t d3_handle_alloc(int kind, const char *name, uint64_t arg) {
    for (uint32_t index = 0; index < HANDLE_SLOTS; index++) {
        Object *object = &g_obj[index];
        if (object->kind != D3_OBJ_NONE)
            continue;
        object->kind = kind;
        object->arg = arg;
        snprintf(object->name, NAME_CHARS, "%s", name != 0 ? name : "");
        return D3_HANDLE_FIRST + index;
    }
    slog("handle table is full");
    return 0;
}

int d3_handle_kind(uint32_t handle) {
    Object *object = object_of(handle);
    return object != 0 ? object->kind : D3_OBJ_NONE;
}

const char *d3_handle_name(uint32_t handle) {
    Object *object = object_of(handle);
    return object != 0 ? object->name : "";
}

uint64_t d3_handle_arg(uint32_t handle) {
    Object *object = object_of(handle);
    return object != 0 ? object->arg : 0;
}

void d3_handle_set_arg(uint32_t handle, uint64_t arg) {
    Object *object = object_of(handle);
    if (object != 0)
        object->arg = arg;
}

int d3_handle_close(uint32_t handle) {
    if (handle < D3_HANDLE_FIRST)
        return 0;
    uint32_t index = handle - D3_HANDLE_FIRST;
    if (index >= HANDLE_SLOTS || g_obj[index].kind == D3_OBJ_NONE)
        return 1;
    g_obj[index].kind = D3_OBJ_NONE;
    g_obj[index].arg = 0;
    g_obj[index].name[0] = 0;
    return 0;
}

void d3_handle_dump(void) {
    for (uint32_t index = 0; index < HANDLE_SLOTS; index++) {
        Object *object = &g_obj[index];
        if (object->kind == D3_OBJ_NONE)
            continue;
        slog("handle %#x kind=%d arg=%#" PRIx64 " name=%s", D3_HANDLE_FIRST + index, object->kind,
             object->arg, object->name);
    }
}

/* -------------------------------------------------------------------- ports */

static int port_kind(const char *name) {
    if (strcmp(name, "sm:") == 0)
        return PORT_SM;
    if (strcmp(name, "fsp-srv") == 0)
        return PORT_FSP;
    if (strcmp(name, "lm") == 0 || strcmp(name, "lm:") == 0)
        return PORT_LM;
    static const char *const offline[] = {
        "nifm", "bsd", "ssl", "nsd", "ldn", "htcs", "bcat", "nfp", "irs", "socket",
    };
    for (size_t i = 0; i < sizeof offline / sizeof offline[0]; i++) {
        size_t len = strlen(offline[i]);
        if (strncmp(name, offline[i], len) == 0 && (name[len] == 0 || name[len] == ':'))
            return PORT_OFFLINE;
    }
    return PORT_UNKNOWN;
}

/* Which interface object id 1 of a converted session stands for. */
static int port_iface(const char *name) {
    if (strcmp(name, "sm:") == 0)
        return D3_IF_SM;
    if (strcmp(name, "appletOE") == 0)
        return D3_IF_APPLET_OE;
    if (strcmp(name, "aoc:u") == 0)
        return D3_IF_AOC;
    if (strncmp(name, "pctl", 4) == 0)
        return D3_IF_PCTL;
    if (strcmp(name, "fsp-srv") == 0)
        return D3_IF_FSP_SRV;
    if (strcmp(name, "lm") == 0)
        return D3_IF_LM;
    if (strcmp(name, "ILogger") == 0)
        return D3_IF_LOGGER;
    if (strcmp(name, "apm") == 0)
        return D3_IF_APM;
    return D3_IF_NONE;
}

static uint32_t port_error(int kind) {
    switch (kind) {
    case PORT_OFFLINE:
        return D3_RESULT(110, 1); /* module NIFM, "not connected" */
    default:
        return D3_RESULT(120, 1); /* module CMIF, "unsupported" */
    }
}

/* ----------------------------------------------------------------- messages */

typedef struct {
    uint64_t address;
    uint32_t w[MESSAGE_WORDS];
    uint32_t type;          /* hipc command type: 6 request, 7 control, 2 close */
    int has_special;
    int has_pid;
    uint32_t copy_handles;
    uint32_t move_handles;
    size_t handle_slot;     /* first handle slot of the request */
    size_t frame;           /* 16 byte aligned word after the header block */
    int domain;             /* the request carried a domain message header */
    uint32_t domain_command;/* 1 = SendMessage, 2 = CloseVirtualHandle */
    uint32_t domain_object;
    size_t magic;           /* word index of the CMIF payload */
    uint32_t command;
    size_t payload;         /* where a reply must put its CMIF payload */
    size_t handle_slot_out;
} Message;

/* HIPC layout in 32-bit words:
   w0          command type and X/A/B/W descriptor counts
   w1          bit31 = special header, bits 0..9 = raw data words
   w2          optional special header
   ...         optional process id, copy handles, then move handles
   ...         X descriptors (2 words each), then A/B/W descriptors (3 each)
   frame       raw data index rounded up to a 16-byte boundary
   frame..     domain header (4 words) for domain messages
   payload     SFCI/SFCO, version, command/result, token, arguments

   Descriptors are outside raw data and must not be searched for CMIF magic. */
static int message_parse(Message *m, uint64_t address) {
    memcpy(m->w, (const void *)(uintptr_t)address, MESSAGE_BYTES);
    m->address = address;
    m->type = m->w[0] & 0xffffu;
    m->has_special = (m->w[1] & 0x80000000u) != 0;
    m->has_pid = 0;
    m->copy_handles = 0;
    m->move_handles = 0;
    size_t index = 2;
    if (m->has_special) {
        const uint32_t special = m->w[2];
        m->has_pid = (int)(special & 1u);
        m->copy_handles = (special >> 1) & 0xfu;
        m->move_handles = (special >> 5) & 0xfu;
        index = 3;
    }
    if (m->has_pid)
        index += 2;
    m->handle_slot = index;
    index += m->copy_handles + m->move_handles;

    const uint32_t descriptor_counts = m->w[0] >> 16;
    const size_t statics = descriptor_counts & 0xfu;
    const size_t sends = (descriptor_counts >> 4) & 0xfu;
    const size_t receives = (descriptor_counts >> 8) & 0xfu;
    const size_t exchanges = (descriptor_counts >> 12) & 0xfu;
    index += 2u * statics + 3u * (sends + receives + exchanges);
    const size_t raw_words = m->w[1] & 0x3ffu;
    if (index > MESSAGE_WORDS || raw_words > MESSAGE_WORDS - index) {
        slog("HIPC layout exceeds message at %#" PRIx64 ": descriptors=%#x raw=%zu", address,
             descriptor_counts, raw_words);
        return -1;
    }
    const size_t raw_end = index + raw_words;
    m->frame = (index + 3u) & ~(size_t)3u;
    m->domain = 0;
    m->domain_command = 0;
    m->domain_object = 0;
    m->magic = 0;

    /* A close has no CMIF payload; stale magic must not turn an invalid close
       into a request. Header 2 also requires zero input objects and data bytes. */
    if ((m->type == 4u || m->type == 6u) && m->frame + 4u <= raw_end &&
        (m->w[m->frame] & 0xffu) == 2u) {
        if (m->w[m->frame] != 2u || descriptor_counts != 0u) {
            slog("malformed domain close at %#" PRIx64, address);
            return -1;
        }
        m->domain = 1;
        m->domain_command = 2;
        m->domain_object = m->w[m->frame + 1];
        m->command = 0;
        m->magic = m->frame;
        return 0;
    }

    if (m->frame + 4u <= raw_end && m->w[m->frame] == CMIF_IN) {
        m->magic = m->frame;
    } else if (m->frame + 8u <= raw_end && (m->w[m->frame] & 0xffu) == 1u &&
               m->w[m->frame + 4] == CMIF_IN) {
        const size_t data_bytes = m->w[m->frame] >> 16;
        const size_t objects = (m->w[m->frame] >> 8) & 0xffu;
        if (data_bytes < 16u ||
            m->frame + 4u + (data_bytes + 3u) / 4u + objects > raw_end) {
            slog("domain payload exceeds raw data at %#" PRIx64, address);
            return -1;
        }
        m->magic = m->frame + 4;
        m->domain = 1;
        m->domain_command = 1;
        m->domain_object = m->w[m->frame + 1];
    }
    /* Legacy handlers and diagnostics inspect up to five argument words. */
    if (m->magic == 0 || m->magic + 9u > MESSAGE_WORDS) {
        slog("no bounded CMIF request at %#" PRIx64, address);
        d3_service_dump("request", address, m->w, MESSAGE_BYTES);
        return -1;
    }
    m->command = m->w[m->magic + 2];
    return 0;
}

static void message_write(const Message *m) {
    memcpy((void *)(uintptr_t)m->address, m->w, MESSAGE_BYTES);
}

/* Replies describe their own handle/header shape; request buffer descriptors
   are consumed server-side and must not appear in the reply header. */
static void reply_prepare(Message *m, uint32_t move_handles, uint32_t params, int domain) {
    const uint32_t tag = m->w[0] & 0xffffu;
    const uint32_t token = m->w[m->magic + 3];
    const bool special = m->has_special || move_handles != 0;
    const bool pid = special && m->has_pid;
    const size_t slot = 2 + (special ? 1u : 0u) + (pid ? 2u : 0u);
    const size_t end = slot + move_handles;
    const size_t frame = (end + 3u) & ~(size_t)3u;
    const size_t payload = frame + (domain ? 4u : 0u);
    for (size_t index = 0; index < MESSAGE_WORDS; index++)
        m->w[index] = 0;
    m->w[0] = tag;
    m->w[1] = (special ? 0x80000000u : 0u) | (uint32_t)(payload + 4 + params);
    if (special)
        m->w[2] = (pid ? 1u : 0u) | ((move_handles & 0xfu) << 5);
    if (domain)
        m->w[frame] = 1; /* one new object id was handed out */
    m->w[payload] = CMIF_OUT;
    m->w[payload + 1] = 1;
    m->w[payload + 2] = 0;
    m->w[payload + 3] = token;
    m->w[payload + 4] = 0;
    m->payload = payload;
    m->handle_slot_out = slot;
    m->frame = frame;
}

static void reply_send(Message *m) {
    if (g_replies < 6) {
        g_replies++;
        slog("cmif-out magic=+%#zx words+0: %#x %#x %#x %#x %#x %#x %#x %#x %#x %#x %#x %#x "
             "%#x %#x %#x %#x",
             m->payload * 4, m->w[0], m->w[1], m->w[2], m->w[3], m->w[4], m->w[5], m->w[6], m->w[7],
             m->w[8], m->w[9], m->w[10], m->w[11], m->w[12], m->w[13], m->w[14], m->w[15]);
        d3_service_dump("cmif-out", m->address, m->w, 0x30);
    }
    g_last_result = m->w[m->payload + 2];
    message_write(m);
}

static void reply_result(Message *m, uint32_t result) {
    reply_prepare(m, 0, 1, 0);
    m->w[m->payload + 2] = result;
    reply_send(m);
}

static void reply_handle(Message *m, uint32_t handle) {
    reply_prepare(m, 1, 1, 0);
    m->w[m->handle_slot_out] = handle;
    m->w[m->payload + 4] = handle;
    reply_send(m);
}

/* A domain reply answers the request's domain header with its own, then the
   CMIF payload; an out interface travels as a new object id at payload + 4. */
static void reply_domain(Message *m, uint32_t result, uint32_t params) {
    reply_prepare(m, 0, params, 1);
    m->w[m->payload + 2] = result;
    reply_send(m);
}

static void reply_domain_object(Message *m, uint32_t object) {
    reply_prepare(m, 0, 2, 1);
    m->w[m->payload + 4] = object;
    reply_send(m);
}

/* An out handle is not a domain object: it travels in the HIPC handle slot,
   even when the session itself has already been converted to a domain. */
static void reply_domain_handle(Message *m, uint32_t handle) {
    reply_prepare(m, 1, 1, 1);
    m->w[m->handle_slot_out] = handle;
    reply_send(m);
}

/* The command name tables come out of the guest's own client stubs (see
   tools/gen_service_names.py), so an unimplemented command can be logged by the
   name the title calls it instead of by a bare number. */
static const char *iface_name(int iface) {
    for (size_t index = 0; index < D3_COMMAND_SET_COUNT; index++) {
        if (d3_command_sets[index].iface == iface)
            return d3_command_sets[index].name;
    }
    return "unknown";
}

static const char *command_name(int iface, uint32_t command) {
    for (size_t index = 0; index < D3_COMMAND_SET_COUNT; index++) {
        const d3_command_set *set = &d3_command_sets[index];
        if (set->iface != iface)
            continue;
        for (uint32_t slot = 0; slot < set->count; slot++) {
            if (set->commands[slot].command == command)
                return set->commands[slot].name;
        }
        break;
    }
    return "?";
}

/* Answer the way a service that does not know a command does.  The callers log
   their own line first, so this only builds the reply. */
static void unsupported_reply(Message *m, int kind) {
    if (m->domain)
        reply_domain(m, port_error(kind), 1);
    else
        reply_result(m, port_error(kind));
}

static void reply_unsupported(const Message *m, const char *port, uint32_t command, int kind) {
    if (g_loud < 4096) {
        g_loud++;
        slog("unimplemented %s cmd=%u args=%#x %#x %#x %#x", port, command, m->w[m->magic + 4],
             m->w[m->magic + 5], m->w[m->magic + 6], m->w[m->magic + 7]);
        d3_service_dump(port, m->address, m->w, 0x80);
    }
    unsupported_reply((Message *)m, kind);
}

/* Log an unimplemented service command that the domain layer reached. */
static void unsupported_command(Message *m, int iface, uint32_t command) {
    if (g_loud < 4096) {
        g_loud++;
        slog("unimplemented %s cmd=%#x (%s) args=%#x %#x %#x %#x", iface_name(iface), command,
             command_name(iface, command), m->w[m->magic + 4], m->w[m->magic + 5],
             m->w[m->magic + 6], m->w[m->magic + 7]);
        d3_service_dump(iface_name(iface), m->address, m->w, 0x80);
    }
    unsupported_reply(m, PORT_UNKNOWN);
}

/* The hipc command type sits in the low half of the first header word.  Type 7
   is ControlWithContext and type 5 is Control; 6/4 are the request forms and 2
   is Close.  A control command is not a service command: the kernel's
   IpcController answers it before the service ever sees the message. */
static int message_is_control(const Message *m) {
    return m->type == 3 || m->type == 5 || m->type == 7;
}

/* Defined with the domain layer below, used here when a session converts. */
static uint32_t domain_add(uint32_t session, int iface);

/* IpcController, exactly the five commands the guest can send.  The guest asks
   for the pointer buffer size right after sm:GetService, so that one has to
   answer with a size (citron computes 0x1000) or the sf client refuses the
   service.  ConvertCurrentObjectToDomain answers with the initial object count
   of 1; the clone commands hand back a second session on the same port. */
static void control_command(Message *m, uint32_t command, uint32_t handle) {
    const char *name = d3_handle_name(handle);
    switch (command) {
    case 0: /* ConvertCurrentObjectToDomain */
        {
            uint32_t object = domain_add(handle, port_iface(name));
            if (object == 0) {
                /* No free domain slot: report the failure, never a fabricated
                   object id, or the guest would address an object that is not
                   there. */
                slog("control %s ConvertCurrentObjectToDomain -> domain table full", name);
                reply_result(m, D3_RESULT(21, 7)); /* module SPRL / no memory */
                break;
            }
            slog("control %s ConvertCurrentObjectToDomain -> object %u (%d)", name, object,
                 port_iface(name));
            reply_prepare(m, 0, 2, 0);
            m->w[m->payload + 4] = object;
            reply_send(m);
        }
        break;
    case 2: /* CloneCurrentObject */
    case 4: /* CloneCurrentObjectEx */
        slog("control %s CloneCurrentObject", name);
        {
            uint32_t clone = d3_handle_alloc(D3_OBJ_SESSION, name, d3_handle_arg(handle));
            if (clone == 0) {
                reply_result(m, D3_RESULT(21, 7));
                break;
            }
            reply_handle(m, clone);
        }
        break;
    case 3: /* QueryPointerBufferSize */
        slog("control %s QueryPointerBufferSize -> 0x1000", name);
        reply_prepare(m, 0, 2, 0);
        m->w[m->payload + 4] = 0x1000;
        reply_send(m);
        break;
    default: /* 1 = CopyFromCurrentDomain, never seen so far */
        reply_unsupported(m, name, command, (int)d3_handle_arg(handle));
        break;
    }
}

/* -------------------------------------------------------------------- sm:  */

static void name_of_param(const Message *m, size_t word, char *out, size_t size) {
    const uint8_t *bytes = (const uint8_t *)&m->w[m->magic + 4 + word];
    size_t n = 0;
    for (size_t i = 0; i < 8 && n + 1 < size; i++) {
        if (bytes[i] >= 0x20 && bytes[i] < 0x7f)
            out[n++] = (char)bytes[i];
    }
    out[n] = 0;
}

static void sm_command(Message *m, uint32_t command) {
    char name[16];
    switch (command) {
    case 0:
        slog("sm:Initialize");
        reply_result(m, 0);
        break;
    case 1:
        name_of_param(m, 0, name, sizeof name);
        slog("sm:GetService name=%s", name);
        {
            int kind = port_kind(name);
            uint32_t handle = d3_handle_alloc(D3_OBJ_SESSION, name, (uint64_t)kind);
            if (handle == 0) {
                reply_result(m, D3_RESULT(21, 7));
                break;
            }
            slog("sm:GetService %s -> handle %#x (kind %d)", name, handle, kind);
            reply_handle(m, handle);
        }
        break;
    case 2:
        name_of_param(m, 0, name, sizeof name);
        slog("sm:RegisterService name=%s", name);
        reply_result(m, 0);
        break;
    case 3:
        name_of_param(m, 0, name, sizeof name);
        slog("sm:UnregisterService name=%s", name);
        reply_result(m, 0);
        break;
    default:
        reply_unsupported(m, "sm:", command, PORT_SM);
        break;
    }
}

static void fsp_command(Message *m, uint32_t command) {
    reply_unsupported(m, "fsp-srv", command, PORT_FSP);
}

/* -------------------------------------------------------------------- lm:  */

/* lm:OpenLogger hands back a session for ILogger.  The logger itself only has
   Log (0) and SetDestination (1); the packets are binary and we do not care
   about them beyond proving the service answers. */
static void logger_command(Message *m, uint32_t command) {
    switch (command) {
    case 0: {
        if (g_loud < 16) {
            g_loud++;
            slog("ILogger::Log size=%u first=%#x %#x %#x %#x", m->w[m->magic + 4],
                 m->w[m->magic + 5], m->w[m->magic + 6], m->w[m->magic + 7], m->w[m->magic + 8]);
        }
        reply_result(m, 0);
        break;
    }
    case 1:
        slog("ILogger::SetDestination");
        reply_result(m, 0);
        break;
    default:
        reply_unsupported(m, "ILogger", command, PORT_LOGGER);
        break;
    }
}

static void lm_command(Message *m, uint32_t command) {
    switch (command) {
    case 0: {
        uint32_t handle = d3_handle_alloc(D3_OBJ_SESSION, "ILogger", PORT_LOGGER);
        if (handle == 0) {
            reply_result(m, D3_RESULT(21, 7));
            break;
        }
        slog("lm:OpenLogger -> handle %#x", handle);
        reply_handle(m, handle);
        break;
    }
    default:
        reply_unsupported(m, "lm:", command, PORT_LM);
        break;
    }
}

/* ----------------------------------------------------------------- domain  */

/* Objects a converted session handed to the guest.  The id the guest uses is
   the slot index plus one, the same convention as citron's domain handlers. */
#define DOMAIN_SLOTS 256

typedef struct {
    int used;
    uint32_t session;
    int iface;
    uint32_t pending; /* queued ReceiveMessage messages not yet consumed */
    int out_of_focus_suspending; /* ISelfController::SetOutOfFocusSuspendingEnabled */
    int initialized; /* a service object the guest has been told is ready */
} DomainObject;

static DomainObject g_domain[DOMAIN_SLOTS];

/* A freshly opened ICommonStateGetter owes the guest one queued message: the
   guest's applet loop calls ReceiveMessage until it sees AppletMessage::
   FocusStateChanged (15) and only then continues booting.  Every other object
   starts with an empty queue. */
#define D3_APPLET_MESSAGE_FOCUS_CHANGED 15u

/* The service object behind pctl's factory commands.  It is a domain object of
   its own so the guest addresses it by id, but its interface tag is a host-only
   value kept out of the generated names header. */
#define D3_IF_PCTL_SERVICE 0x10000

static uint32_t domain_add(uint32_t session, int iface) {
    for (uint32_t index = 0; index < DOMAIN_SLOTS; index++) {
        DomainObject *object = &g_domain[index];
        if (object->used)
            continue;
        object->used = 1;
        object->session = session;
        object->iface = iface;
        object->pending =
            iface == D3_IF_COMMON_STATE_GETTER ? D3_APPLET_MESSAGE_FOCUS_CHANGED : 0u;
        object->out_of_focus_suspending = 0;
        object->initialized = 0;
        return index + 1;
    }
    slog("domain table is full");
    return 0;
}

static int domain_iface(uint32_t session, uint32_t id) {
    if (id == 0 || id > DOMAIN_SLOTS)
        return D3_IF_NONE;
    DomainObject *object = &g_domain[id - 1];
    return object->used && object->session == session ? object->iface : D3_IF_NONE;
}

static void domain_close(uint32_t session, uint32_t id) {
    if (id == 0 || id > DOMAIN_SLOTS)
        return;
    DomainObject *object = &g_domain[id - 1];
    if (object->used && object->session == session) {
        object->used = 0;
        object->iface = D3_IF_NONE;
        object->pending = 0;
        object->out_of_focus_suspending = 0;
        object->initialized = 0;
    }
}

/* Pop the oldest message queued on one domain object, or 0 when the object has
   none (or the id does not belong to this session).  Today the only queued
   message is the focus notification, so the value returned is the applet
   message kind the guest's ReceiveMessage loop is waiting for. */
static uint32_t domain_take_pending(uint32_t session, uint32_t id) {
    if (id == 0 || id > DOMAIN_SLOTS)
        return 0;
    DomainObject *object = &g_domain[id - 1];
    if (!object->used || object->session != session)
        return 0;
    uint32_t message = object->pending;
    object->pending = 0;
    return message;
}

/* Record one ISelfController::SetOutOfFocusSuspendingEnabled value on the object
   it was sent to, so objects stay independent and the setting survives until the
   object is closed.  Out of range ids are ignored; the caller still replies. */
static void domain_set_out_of_focus_suspending(uint32_t session, uint32_t id, int enabled) {
    if (id == 0 || id > DOMAIN_SLOTS)
        return;
    DomainObject *object = &g_domain[id - 1];
    if (object->used && object->session == session)
        object->out_of_focus_suspending = enabled;
}

/* Mark a pctl service object ready.  Factory command 1 (CreateServiceWithout-
   Initialize) hands out an object the guest then initializes with child command
   1; factory command 0 hands out one that is already initialized. */
static void domain_set_initialized(uint32_t session, uint32_t id, int initialized) {
    if (id == 0 || id > DOMAIN_SLOTS)
        return;
    DomainObject *object = &g_domain[id - 1];
    if (object->used && object->session == session)
        object->initialized = initialized;
}

/* pctl (parental controls).  The guest boot path only needs the factory pair: on
   HOS >= 4 the client sends factory command 1 (CreateServiceWithoutInitialize)
   with a u64 pid_reserved and a matching pid, then calls the new service object's
   Initialize (child command 1).  Anything else is left to the regular
   unimplemented-command reply so a policy getter is never silently accepted. */
static void pctl_command(Message *m, uint32_t command, uint32_t session) {
    const uint32_t pid_reserved = m->w[m->magic + 4];
    const uint32_t pid_high = m->w[m->magic + 5];
    switch (command) {
    case 0:
    case 1: { /* CreateService / CreateServiceWithoutInitialize */
        const int preinitialized = command == 0;
        uint32_t object = domain_add(session, D3_IF_PCTL_SERVICE);
        if (object == 0) {
            slog("IParentalControlService::%s -> domain table full", "CreateService");
            reply_domain(m, D3_RESULT(21, 7), 1);
            break;
        }
        /* Factory 0 returns a ready object; factory 1 returns one the guest then
           initializes (child command 1). */
        domain_set_initialized(session, object, preinitialized);
        slog("IParentalControlService factory cmd=%u pid_reserved=%#" PRIx32 "/%#" PRIx32
             " -> object %u (initialized %d)",
             command, pid_reserved, pid_high, object, preinitialized);
        reply_domain_object(m, object);
        break;
    }
    default:
        slog("IParentalControlService factory cmd=%u -> unsupported", command);
        unsupported_command(m, D3_IF_PCTL, command);
        break;
    }
}

/* A pctl service object, reached as the object one of the factory commands above
   handed out. */
static void pctl_service_command(Message *m, uint32_t command, uint32_t session) {
    switch (command) {
    case 1: /* Initialize */
        domain_set_initialized(session, m->domain_object, 1);
        slog("IParentalControlService::Initialize -> object %u ready", m->domain_object);
        reply_domain(m, 0, 1);
        break;
    default:
        unsupported_command(m, D3_IF_PCTL_SERVICE, command);
        break;
    }
}

/* IApplicationProxyService, reached as object 1 of appletOE. */
static void applet_oe_command(Message *m, uint32_t command, uint32_t session) {
    switch (command) {
    case 0: { /* OpenApplicationProxy (Out<SharedPointer<IApplicationProxy>>, pid, handle) */
        uint32_t object = domain_add(session, D3_IF_APPLICATION_PROXY);
        slog("IApplicationProxyService::OpenApplicationProxy -> object %u", object);
        reply_domain_object(m, object);
        break;
    }
    default:
        unsupported_command(m, D3_IF_APPLET_OE, command);
        break;
    }
}

/* IApplicationProxy, reached as the object OpenApplicationProxy handed out.
   Every command it has hands out another interface, so the reply carries a new
   object id. */
static void application_proxy_command(Message *m, uint32_t command, uint32_t session) {
    static const struct {
        uint32_t command;
        int iface;
    } table[] = {
        {0, D3_IF_COMMON_STATE_GETTER},
        {1, D3_IF_SELF_CONTROLLER},
        {2, D3_IF_WINDOW_CONTROLLER},
        {3, D3_IF_AUDIO_CONTROLLER},
        {4, D3_IF_DISPLAY_CONTROLLER},
        {10, D3_IF_PROCESS_WINDING_CONTROLLER},
        {11, D3_IF_LIBRARY_APPLET_CREATOR},
        {0x3e8, D3_IF_DEBUG_FUNCTIONS},
        {20, D3_IF_APPLICATION_FUNCTIONS},
    };
    for (size_t index = 0; index < sizeof table / sizeof table[0]; index++) {
        if (table[index].command != command)
            continue;
        uint32_t object = domain_add(session, table[index].iface);
        slog("IApplicationProxy::%s -> object %u",
             command_name(D3_IF_APPLICATION_PROXY, command), object);
        reply_domain_object(m, object);
        return;
    }
    unsupported_command(m, D3_IF_APPLICATION_PROXY, command);
}

/* nn::settings::LanguageCode is the system language code packed into a u64, not
   the old numeric enum: "en-US" is 0x00000053552D6E65. */
#define D3_LANGUAGE_EN_US 0x00000053552D6E65ull

/* What GetDisplayVersion answers with (nn::oe::DisplayVersion is a sixteen byte
   string). */
#define D3_DISPLAY_VERSION "18.1.0"

/* IApplicationFunctions, the interface IApplicationProxy::GetApplicationFunctions
   hands out.  The boot path asks for the system language and the display version
   as soon as it has the interface, and reports the terminate result when it
   stops, so those three are implemented and everything else is logged by name. */
static void application_functions_command(Message *m, uint32_t command, uint32_t session) {
    (void)session;
    switch (command) {
    case 21: { /* GetDesiredLanguage (Out<settings::LanguageCode>) */
        slog("IApplicationFunctions::GetDesiredLanguage -> en-US");
        reply_prepare(m, 0, 2, 1);
        m->w[m->payload + 4] = (uint32_t)D3_LANGUAGE_EN_US;
        m->w[m->payload + 5] = (uint32_t)(D3_LANGUAGE_EN_US >> 32);
        reply_send(m);
        break;
    }
    case 22: /* SetTerminateResult (u32), nothing comes back */
        reply_domain(m, 0, 1);
        break;
    case 23: { /* GetDisplayVersion (Out<oe::DisplayVersion>, 0x10 bytes) */
        static const char version[0x10] = D3_DISPLAY_VERSION;
        slog("IApplicationFunctions::GetDisplayVersion -> %s", version);
        reply_prepare(m, 0, 4, 1);
        for (size_t word = 0; word < 4; word++)
            memcpy(&m->w[m->payload + 4 + word], version + 4 * word, 4);
        reply_send(m);
        break;
    }
    case 0x82: {
        uint32_t event = d3_handle_alloc(D3_OBJ_EVENT, "gpu-error", 0);
        slog("IApplicationFunctions::GetGpuErrorDetectedSystemEvent -> handle %#x",
             event);
        if (event == 0)
            reply_domain(m, D3_RESULT(21, 7), 1);
        else
            reply_domain_handle(m, event);
        break;
    }
    default:
        unsupported_command(m, D3_IF_APPLICATION_FUNCTIONS, command);
        break;
    }
}

/* Minimal applet-controller shapes checked against citron; Android emulates an
   application running handheld and in focus. */
static void common_state_getter_command(Message *m, uint32_t command, uint32_t session) {
    switch (command) {
    case 0: {
        uint32_t event = d3_handle_alloc(D3_OBJ_EVENT, "applet-state", 0);
        slog("ICommonStateGetter::GetEventHandle -> handle %#x", event);
        if (event == 0)
            reply_domain(m, D3_RESULT(21, 7), 1);
        else
            reply_domain_handle(m, event);
        break;
    }
    case 1: { /* ReceiveMessage (Out<AppletMessage>) */
        uint32_t message = domain_take_pending(session, m->domain_object);
        if (message != 0) {
            slog("ICommonStateGetter::ReceiveMessage -> %u (FocusStateChanged)", message);
            reply_prepare(m, 0, 2, 1);
            m->w[m->payload + 4] = message;
            reply_send(m);
        } else {
            slog("ICommonStateGetter::ReceiveMessage -> no messages");
            reply_domain(m, D3_RESULT(128, 3), 1);
        }
        break;
    }
    case 3:
    case 4:
    case 10:
        slog("ICommonStateGetter cmd=%u (%s)", command,
             command_name(D3_IF_COMMON_STATE_GETTER, command));
        reply_domain(m, 0, 1);
        break;
    case 5:
    case 6:
    case 8:
        slog("ICommonStateGetter cmd=%u (%s) -> 0", command,
             command_name(D3_IF_COMMON_STATE_GETTER, command));
        reply_prepare(m, 0, 2, 1);
        m->w[m->payload + 4] = 0;
        reply_send(m);
        break;
    case 9:
        slog("ICommonStateGetter::GetCurrentFocusState -> in focus");
        reply_prepare(m, 0, 2, 1);
        m->w[m->payload + 4] = 1;
        reply_send(m);
        break;
    default:
        unsupported_command(m, D3_IF_COMMON_STATE_GETTER, command);
        break;
    }
}

static void self_controller_command(Message *m, uint32_t command, uint32_t session) {
    switch (command) {
    case 0:
    case 1:
    case 2:
    case 3:
    case 4:
    case 10:
    case 11:
    case 12:
    case 13:
    case 14:
        slog("ISelfController cmd=%u (%s)", command,
             command_name(D3_IF_SELF_CONTROLLER, command));
        reply_domain(m, 0, 1);
        break;
    case 16: { /* SetOutOfFocusSuspendingEnabled(bool) */
        /* The argument is one byte at the first data word; its high bytes are
           padding and must not leak into the value. */
        const int enabled = (m->w[m->magic + 4] & 0xffu) != 0;
        domain_set_out_of_focus_suspending(session, m->domain_object, enabled);
        slog("ISelfController::SetOutOfFocusSuspendingEnabled -> %s",
             enabled ? "true" : "false");
        reply_domain(m, 0, 1);
        break;
    }
    case 9: {
        uint32_t event = d3_handle_alloc(D3_OBJ_EVENT, "applet-launchable", 0);
        slog("ISelfController::GetLibraryAppletLaunchableEvent -> handle %#x", event);
        if (event == 0)
            reply_domain(m, D3_RESULT(21, 7), 1);
        else
            reply_domain_handle(m, event);
        break;
    }
    case 0x28:
        slog("ISelfController::CreateManagedDisplayLayer -> 1");
        reply_prepare(m, 0, 3, 1);
        m->w[m->payload + 4] = 1;
        m->w[m->payload + 5] = 0;
        reply_send(m);
        break;
    case 0x5b: {
        uint32_t event = d3_handle_alloc(D3_OBJ_EVENT, "applet-suspend", 0);
        slog("ISelfController::GetAccumulatedSuspendedTickChangedEvent -> handle %#x",
             event);
        if (event == 0)
            reply_domain(m, D3_RESULT(21, 7), 1);
        else
            reply_domain_handle(m, event);
        break;
    }
    default:
        unsupported_command(m, D3_IF_SELF_CONTROLLER, command);
        break;
    }
}

static void window_controller_command(Message *m, uint32_t command) {
    switch (command) {
    case 1:
    case 2:
        slog("IWindowController::GetAppletResourceUserId%s -> 0",
             command == 2 ? "OfCallerApplet" : "");
        reply_prepare(m, 0, 3, 1);
        m->w[m->payload + 4] = 0;
        m->w[m->payload + 5] = 0;
        reply_send(m);
        break;
    case 10:
    case 11:
    case 12:
    case 14:
    case 15:
        slog("IWindowController cmd=%u (%s)", command,
             command_name(D3_IF_WINDOW_CONTROLLER, command));
        reply_domain(m, 0, 1);
        break;
    default:
        unsupported_command(m, D3_IF_WINDOW_CONTROLLER, command);
        break;
    }
}

static void debug_functions_command(Message *m, uint32_t command) {
    switch (command) {
    case 0x0a:
        slog("IDebugFunctions::PerformSystemButtonPressing");
        break;
    case 0x14:
        slog("IDebugFunctions::InvalidateTransitionLayer");
        break;
    case 0x1e:
        slog("IDebugFunctions::RequestLaunchApplicationWithUserAndArgumentForDebug");
        break;
    case 0x28:
        slog("IDebugFunctions::GetAppletResourceUsageInfo");
        break;
    case 0x64:
        slog("IDebugFunctions::SetCpuBoostModeForApplet");
        break;
    default:
        slog("IDebugFunctions cmd=%u -> success", command);
        break;
    }
    reply_domain(m, 0, 1);
}

static void domain_command(Message *m, uint32_t handle) {
    const char *name = d3_handle_name(handle);
    if (m->domain_command == 2) { /* CloseVirtualHandle */
        slog("domain %s close object %u", name, m->domain_object);
        domain_close(handle, m->domain_object);
        reply_domain(m, 0, 1);
        return;
    }
    if (m->domain_command != 1) { /* only SendMessage carries a CMIF payload */
        slog("domain %s unknown message command %u", name, m->domain_command);
        reply_domain(m, D3_RESULT(120, 1), 1);
        return;
    }
    const int iface = domain_iface(handle, m->domain_object);
    if (g_loud < 4096) {
        g_loud++;
        slog("domain %s object %u iface %d cmd %u args=%#x %#x %#x %#x", name, m->domain_object,
             iface, m->command, m->w[m->magic + 4], m->w[m->magic + 5], m->w[m->magic + 6],
             m->w[m->magic + 7]);
    }
    switch (iface) {
    case D3_IF_PCTL:
        pctl_command(m, m->command, handle);
        break;
    case D3_IF_PCTL_SERVICE:
        pctl_service_command(m, m->command, handle);
        break;
    case D3_IF_APPLET_OE:
        applet_oe_command(m, m->command, handle);
        break;
    case D3_IF_COMMON_STATE_GETTER:
        common_state_getter_command(m, m->command, handle);
        break;
    case D3_IF_SELF_CONTROLLER:
        self_controller_command(m, m->command, handle);
        break;
    case D3_IF_WINDOW_CONTROLLER:
        window_controller_command(m, m->command);
        break;
    case D3_IF_DEBUG_FUNCTIONS:
        debug_functions_command(m, m->command);
        break;
    case D3_IF_APPLICATION_PROXY:
        application_proxy_command(m, m->command, handle);
        break;
    case D3_IF_APPLICATION_FUNCTIONS:
        application_functions_command(m, m->command, handle);
        break;
    case D3_IF_NONE:
        slog("domain %s has no object %u (iface %d)", name, m->domain_object, iface);
        reply_domain(m, D3_RESULT(121, 1), 1);
        break;
    default:
        /* An interface the host knows by name but has not implemented yet. */
        unsupported_command(m, iface, m->command);
        break;
    }
}

/* ------------------------------------------------------------------- sync  */

/* A guest that keeps re sending a request that just failed would spin every
   core for as long as the battery lasts, so stop the host when one request
   repeats after a failure.  Successful repeats (the game polling a service)
   do not count. */
#define D3_REPEAT_LIMIT 1200

static void repeat_guard(const Message *m, uint32_t handle) {
    uint64_t signature = ((uint64_t)handle << 40) ^ ((uint64_t)m->type << 32);
    signature ^= ((uint64_t)m->command << 16) ^ ((uint64_t)m->domain_object << 8);
    signature ^= m->w[m->magic + 4];
    if (signature != g_last_signature) {
        g_last_signature = signature;
        g_last_repeats = 1;
        return;
    }
    if (g_last_result == 0 || ++g_last_repeats < D3_REPEAT_LIMIT)
        return;
    slog("port=%s handle %#x cmd=%u failed and repeated %u times: stopping the host",
         d3_handle_name(handle), handle, m->command, g_last_repeats);
    __android_log_print(ANDROID_LOG_ERROR, LOG_TAG,
                        "repeated failing request on %s cmd=%u: stopping",
                        d3_handle_name(handle), m->command);
    abort();
}

static void send_sync(d3_saved *saved, uint64_t buffer, uint32_t handle, const char *which) {
    const char *name = d3_handle_name(handle);
    int kind = d3_handle_kind(handle);
    if (kind != D3_OBJ_SESSION) {
        slog("SendSyncRequest on handle %#x (%s) kind %d", handle, name, kind);
        saved->x[0] = D3_RESULT(11, 1); /* module HIPC, "invalid handle" */
        return;
    }
    Message m;
    if (message_parse(&m, buffer) != 0) {
        slog("%s handle %#x (%s) kind %d buffer %#" PRIx64 ": no CMIF request", which, handle, name,
             kind, buffer);
        /* HIPC session Close has no CMIF payload, unlike a service request. */
        const uint32_t *words = (const uint32_t *)(uintptr_t)buffer;
        if (words[0] == 2u && words[1] == 0u) {
            uint32_t reply[MESSAGE_WORDS];
            memset(reply, 0, sizeof reply);
            reply[0] = words[0];
            memcpy((void *)(uintptr_t)buffer, reply, sizeof reply);
            slog("%s bare header on %s tag=%u -> empty reply", which, name, words[0] & 0xffffu);
            saved->x[0] = 0;
            return;
        }
        saved->x[0] = D3_RESULT(11, 2);
        return;
    }
    if (g_loud < 4096) {
        g_loud++;
        slog("cmif port=%s cmd=%u tag=%u magic=+%#zx words0..15=%#x %#x %#x %#x %#x %#x %#x %#x "
             "%#x %#x %#x %#x %#x %#x %#x %#x",
             name, m.command, m.w[0] & 0xffffu, m.magic * 4, m.w[0], m.w[1], m.w[2], m.w[3], m.w[4],
             m.w[5], m.w[6],
             m.w[7], m.w[8], m.w[9], m.w[10], m.w[11], m.w[12], m.w[13], m.w[14], m.w[15]);
        d3_service_dump("cmif-in", buffer, m.w, MESSAGE_BYTES);
        d3_trace_guest(name, saved);
    }
    repeat_guard(&m, handle);
    if (message_is_control(&m)) {
        control_command(&m, m.command, handle);
        saved->x[0] = 0;
        return;
    }
    if (m.domain) {
        domain_command(&m, handle);
        saved->x[0] = 0;
        return;
    }
    switch ((int)d3_handle_arg(handle)) {
    case PORT_SM:
        sm_command(&m, m.command);
        break;
    case PORT_FSP:
        fsp_command(&m, m.command);
        break;
    case PORT_LM:
        lm_command(&m, m.command);
        break;
    case PORT_LOGGER:
        logger_command(&m, m.command);
        break;
    default:
        reply_unsupported(&m, name, m.command, (int)d3_handle_arg(handle));
        break;
    }
    saved->x[0] = 0;
}

void d3_svc_send_sync_request(d3_saved *saved, uint64_t tls) {
    send_sync(saved, tls, (uint32_t)saved->x[0], "SendSyncRequest");
}

void d3_svc_send_sync_request_user(d3_saved *saved) {
    uint64_t buffer = saved->x[0];
    uint32_t handle = (uint32_t)saved->x[2];
    send_sync(saved, buffer, handle, "SendSyncRequestWithUserBuffer");
}

void d3_svc_send_async_request(d3_saved *saved) {
    saved->x[0] = 0;
    saved->x[2] = 0;
    saved->x[3] = 0;
}

/* ---------------------------------------------------------- named ports    */

void d3_svc_connect_to_named_port(d3_saved *saved) {
    uint64_t out = saved->x[0];
    const uint8_t *raw = (const uint8_t *)(uintptr_t)saved->x[1];
    char name[16];
    size_t n = 0;
    for (size_t i = 0; i < 8 && n + 1 < sizeof name; i++) {
        if (raw[i] < 0x20 || raw[i] >= 0x7f)
            break;
        name[n++] = (char)raw[i];
    }
    name[n] = 0;
    slog("ConnectToNamedPort raw=%02x %02x %02x %02x %02x %02x %02x %02x", raw[0], raw[1], raw[2],
         raw[3], raw[4], raw[5], raw[6], raw[7]);
    int kind = port_kind(name);
    if (kind == PORT_UNKNOWN && g_quiet < 64) {
        g_quiet++;
        slog("ConnectToNamedPort unknown port %s", name);
    }
    uint32_t handle = d3_handle_alloc(D3_OBJ_SESSION, name, (uint64_t)kind);
    if (out != 0)
        memcpy((void *)(uintptr_t)out, &handle, sizeof handle);
    slog("ConnectToNamedPort %s -> handle %#x (kind %d)", name, handle, kind);
    saved->x[0] = 0;
    saved->x[1] = handle;
}

/* ------------------------------------------------------------------ start  */

void d3_service_open(void) {
    (void)mkdir(D3_DATA_ROOT, 0777);
    (void)mkdir(LOG_DIR, 0777);
    g_log = open_log();
    g_log_tried = 1;
    slog("service layer up, log %s fd %d", LOG_PATH, g_log);
}
