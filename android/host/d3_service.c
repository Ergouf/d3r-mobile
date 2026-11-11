#define _GNU_SOURCE
#include <pthread.h>

#include "d3_service.h"
#include "d3_service_names.h"
#include "d3_audio.h"
#include "d3_content.h"

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
#include <sys/statvfs.h>
#include <sys/uio.h>
#include <unistd.h>

#define LOG_TAG "D3Host"
#define LOG_DIR D3_DATA_ROOT "/logs"
#define LOG_PATH LOG_DIR "/d3-service.log"

/* The CMIF magic the guest writes into a request and expects in a reply. */
#define CMIF_IN 0x49434653u
#define CMIF_OUT 0x4F434653u
#define MESSAGE_BYTES 0x100
#define MESSAGE_WORDS (MESSAGE_BYTES / 4)
#include "d3_nvdrv.h"
#ifdef D3_WITH_GPU
#include "../gpu/host/gpu_bridge.h"
#endif

/* Horizon result encoding: module in bits 0..8, description in bits 9..21.
   nn::Result treats any non zero value as a failure (nnResultIsFailure). */
#define D3_RESULT(module, description) (((module) & 0x1FFu) | ((description) << 9))

enum {
    PORT_NONE = 0, PORT_SM, PORT_FSP, PORT_LM, PORT_LOGGER, PORT_OFFLINE,
    PORT_UNKNOWN, PORT_SET, PORT_TIME, PORT_TIME_ZONE, PORT_NVDRV, PORT_VI_MGR, PORT_VI_APP,
    PORT_HID, PORT_AOC, PORT_ACCOUNT, PORT_HID_APPLET_RESOURCE, PORT_APM, PORT_APM_SESSION,
    PORT_BINDER, PORT_AUDOUT, PORT_AUDIO_OUT, PORT_AUDIN, PORT_FRIEND, PORT_HID_VIBRATION
};

#define HANDLE_SLOTS 0x400
#define NAME_CHARS 24

/* ------------------------------------------------------------------ logging */

static int g_log = -1;
static int g_log_tried;
static uint32_t g_loud;
static uint32_t g_replies;
static uint32_t g_quiet;
static _Thread_local uint32_t g_last_result;
static uint64_t g_last_signature;
static uint32_t g_last_repeats;
static uint32_t g_cmif_traces;
static uint32_t g_nifm_poll_logs;

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
    /* Identity of the session's domain-object table.  CloneCurrentObject returns
       a second handle to the same session, and the guest then sends its domain
       messages through whichever clone it likes, so domain objects are keyed by
       this and not by the raw handle value. */
    uint32_t domain_key;
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
        object->domain_key = D3_HANDLE_FIRST + index;
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

/* The domain-object table this handle addresses; clones of one session share it. */
uint32_t d3_handle_domain_key(uint32_t handle) {
    Object *object = object_of(handle);
    return object != 0 ? object->domain_key : handle;
}

void d3_handle_set_arg(uint32_t handle, uint64_t arg) {
    Object *object = object_of(handle);
    if (object != 0)
        object->arg = arg;
}

static void domain_close_session(uint32_t session);

int d3_handle_close(uint32_t handle) {
    if (handle < D3_HANDLE_FIRST)
        return 0;
    uint32_t index = handle - D3_HANDLE_FIRST;
    if (index >= HANDLE_SLOTS || g_obj[index].kind == D3_OBJ_NONE)
        return 1;
    if (g_obj[index].kind == D3_OBJ_SESSION)
        domain_close_session(handle);
    if (g_obj[index].kind == D3_OBJ_SESSION && g_obj[index].arg == PORT_AUDIO_OUT) {
        unsigned audio_id = 0;
        if (sscanf(g_obj[index].name, "audio-out-%u", &audio_id) == 1)
            d3_audio_close(audio_id);
    }
    if (g_obj[index].kind == D3_OBJ_EVENT) {
        extern void d3_event_on_close(uint32_t handle);
        d3_event_on_close(handle);
    }
    g_obj[index].kind = D3_OBJ_NONE;
    g_obj[index].arg = 0;
    g_obj[index].domain_key = 0;
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
    if (strcmp(name, "friend:u") == 0)
        return PORT_FRIEND;
    if (strcmp(name, "audin:u") == 0)
        return PORT_AUDIN;
    if (strcmp(name, "audout:u") == 0)
        return PORT_AUDOUT;
    if (strcmp(name, "sm:") == 0)
        return PORT_SM;
    if (strcmp(name, "fsp-srv") == 0)
        return PORT_FSP;
    if (strcmp(name, "lm") == 0 || strcmp(name, "lm:") == 0)
        return PORT_LM;
    if (strcmp(name, "set") == 0 || strcmp(name, "set:") == 0)
        return PORT_SET;
    if (strcmp(name, "nvdrv") == 0)
        return PORT_NVDRV;
    if (strcmp(name, "dispdrv") == 0)
        return PORT_BINDER;
    if (strcmp(name, "hid") == 0)
        return PORT_HID;
    if (strcmp(name, "aoc:u") == 0)
        return PORT_AOC;
    if (strcmp(name, "apm") == 0)
        return PORT_APM;
    if (strcmp(name, "apm-session") == 0)
        return PORT_APM_SESSION;
    /* The engine asks for "acc:u0", not "account": nn::account maps on to the
       acc:uN ports, so both spellings have to select the account service. */
    if (strncmp(name, "account", 7) == 0 || strncmp(name, "acc:", 4) == 0)
        return PORT_ACCOUNT;
    if (strncmp(name, "vi:", 3) == 0)
        return PORT_VI_MGR;
    if (strcmp(name, "time:u") == 0)
        return PORT_TIME;
    if (strcmp(name, "ITimeZoneService") == 0)
        return PORT_TIME_ZONE;
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

/* Host-only tags for interfaces the generated table does not name yet. */
#define D3_IF_NVDRV 0x10003
#define D3_IF_VI_MANAGER 0x10004
#define D3_IF_VI_APP 0x10005
#define D3_IF_ACCOUNT 0x10006
#define D3_IF_NIFM 0x10009
#define D3_IF_HID 0x1000a
#define D3_IF_HID_APPLET_RESOURCE 0x1000b
#define D3_IF_SAVE_FILESYSTEM 0x1000c
#define D3_IF_APM_SESSION 0x10010
#define D3_IF_NIFM_REQUEST 0x1000f
#define D3_IF_NFP_MANAGER 0x10011
#define D3_IF_NFP_USER 0x10012
#define D3_IF_BINDER 0x10013
#define D3_IF_AUDOUT 0x10014
#define D3_IF_AUDIO_OUT 0x10015
#define D3_IF_AUDIN 0x10016
#define D3_IF_FRIEND_CREATOR 0x10017
#define D3_IF_FRIEND 0x10018
#define D3_IF_FRIEND_NOTIFICATION 0x10019
#define D3_IF_HID_VIBRATION 0x1001a

/* Which interface object id 1 of a converted session stands for. */
static int port_iface(const char *name) {
    if (strcmp(name, "friend:u") == 0)
        return D3_IF_FRIEND_CREATOR;
    if (strcmp(name, "audin:u") == 0)
        return D3_IF_AUDIN;
    if (strcmp(name, "audout:u") == 0)
        return D3_IF_AUDOUT;
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
    if (strcmp(name, "apm-session") == 0)
        return D3_IF_APM_SESSION;
    if (strcmp(name, "time:u") == 0)
        return D3_IF_TIME;
    if (strcmp(name, "ITimeZoneService") == 0)
        return D3_IF_TIME_ZONE;
    if (strcmp(name, "hid") == 0)
        return D3_IF_HID;
    if (strcmp(name, "hid-applet") == 0)
        return D3_IF_HID_APPLET_RESOURCE;
    if (strcmp(name, "nvdrv") == 0)
        return D3_IF_NVDRV;
    if (strcmp(name, "dispdrv") == 0)
        return D3_IF_BINDER;
    if (strncmp(name, "vi:", 3) == 0)
        return D3_IF_VI_MANAGER;
    if (strncmp(name, "account", 7) == 0 || strncmp(name, "acc:", 4) == 0)
        return D3_IF_ACCOUNT;
    if (strncmp(name, "nifm:", 5) == 0)
        return D3_IF_NIFM;
    if (strcmp(name, "nfp:user") == 0)
        return D3_IF_NFP_MANAGER;
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
    size_t data_end;
    uint32_t command;
    size_t payload;         /* where a reply must put its CMIF payload */
    size_t handle_slot_out;
    size_t descriptor_slot; /* first buffer descriptor of the request */
    size_t recv_buffer_count;
    size_t recv_buffer_slot;
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
    m->descriptor_slot = index;

    const uint32_t descriptor_counts = m->w[0] >> 16;
    const size_t statics = descriptor_counts & 0xfu;
    const size_t sends = (descriptor_counts >> 4) & 0xfu;
    const size_t receives = (descriptor_counts >> 8) & 0xfu;
    const size_t exchanges = (descriptor_counts >> 12) & 0xfu;
    m->recv_buffer_count = receives;
    m->recv_buffer_slot = index + 2u * statics + 3u * sends;
    index += 2u * statics + 3u * (sends + receives + exchanges);
    const size_t raw_words = m->w[1] & 0x3ffu;
    if (index > MESSAGE_WORDS || raw_words > MESSAGE_WORDS - index) {
        slog("HIPC layout exceeds message at %#" PRIx64 ": descriptors=%#x raw=%zu", address,
             descriptor_counts, raw_words);
        return -1;
    }
    const size_t raw_end = index + raw_words;
    m->data_end = raw_end;
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
        m->data_end = m->magic + data_bytes / 4u;
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

/* Full plain-word dump of one request/reply: the capped per-request logging in
   send_sync cannot show a late request (the loud counter runs out long before the
   boot stops), and a request the host cannot place needs its raw shape. */
static void dump_message(const char *why, const Message *m, uint32_t handle) {
    slog("%s handle=%#x name=%s kind=%d arg=%#" PRIx64 " domain_key=%#x", why, handle,
         d3_handle_name(handle), d3_handle_kind(handle), d3_handle_arg(handle),
         d3_handle_domain_key(handle));
    slog("%s parse type=%u special=%d pid=%d copy=%u move=%u handle_slot=%zu desc_slot=%zu "
         "frame=%zu magic=%zu domain=%d dcmd=%u dobj=%u command=%u payload=%zu",
         why, m->type, m->has_special, m->has_pid, m->copy_handles, m->move_handles,
         m->handle_slot, m->descriptor_slot, m->frame, m->magic, m->domain, m->domain_command,
         m->domain_object, m->command, m->payload);
    for (size_t base = 0; base + 4 <= 16; base += 4)
        slog("%s w%zu: %#x %#x %#x %#x", why, base, m->w[base], m->w[base + 1], m->w[base + 2],
             m->w[base + 3]);
}

/* Read a message the parser took for a domain SendMessage as the plain CMIF
   request its payload really is: the parser only needs the domain shape, so a
   request that carries handle words between the HIPC header and the CMIF magic
   lands there too, and the object id it reports is then just another header word.
   The CMIF payload, its magic and its command sit at frame + 4 either way. */
static int message_plain_at(Message *m) {
    const size_t magic = m->frame + 4;
    const uint32_t counts = m->w[0] >> 16;
    const size_t statics = counts & 0xfu;
    const size_t sends = (counts >> 4) & 0xfu;
    const size_t receives = (counts >> 8) & 0xfu;
    const size_t exchanges = (counts >> 12) & 0xfu;
    const size_t index =
        m->descriptor_slot + 2u * statics + 3u * (sends + receives + exchanges);
    const size_t raw_end = index + (m->w[1] & 0x3ffu);
    if (magic + 9u > MESSAGE_WORDS || magic + 4u > raw_end || m->w[magic] != CMIF_IN)
        return -1;
    m->magic = magic;
    m->domain = 0;
    m->domain_command = 0;
    m->domain_object = 0;
    m->command = m->w[magic + 2];
    return 0;
}

static void message_write(const Message *m) {
    memcpy((void *)(uintptr_t)m->address, m->w, MESSAGE_BYTES);
}

/* Replies describe their own handle/header shape; request buffer descriptors
   are consumed server-side and must not appear in the reply header. */
enum { REPLY_COPY_HANDLE = 0, REPLY_MOVE_HANDLE = 1 };

static void reply_prepare_handle(Message *m, uint32_t handles, uint32_t params, int domain,
                                 int category) {
    const uint32_t tag = m->w[0] & 0xffffu;
    const uint32_t token = m->w[m->magic + 3];
    const bool special = handles != 0;
    const size_t slot = 2 + (special ? 1u : 0u);
    const size_t end = slot + handles;
    const size_t frame = (end + 3u) & ~(size_t)3u;
    const size_t payload = frame + (domain ? 4u : 0u);
    for (size_t index = 0; index < MESSAGE_WORDS; index++)
        m->w[index] = 0;
    m->w[0] = tag;
    m->w[1] = (special ? 0x80000000u : 0u) | (uint32_t)(payload + 4 + params);
    if (special)
        m->w[2] = (handles & 0xfu) << (category == REPLY_MOVE_HANDLE ? 5 : 1);
    m->w[payload] = CMIF_OUT;
    m->w[payload + 1] = 1;
    m->w[payload + 2] = 0;
    m->w[payload + 3] = token;
    m->w[payload + 4] = 0;
    m->payload = payload;
    m->handle_slot_out = slot;
    m->frame = frame;
}

static void reply_prepare(Message *m, uint32_t handles, uint32_t params, int domain) {
    reply_prepare_handle(m, handles, params, domain, REPLY_COPY_HANDLE);
}

static _Thread_local int g_dump_port;

static void reply_send(Message *m) {
    if (g_replies < 6) {
        if (g_replies < 6)
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

static _Thread_local uint64_t g_current_buffer;

uint32_t d3_service_last_result(void) {
    return g_last_result;
}

uint64_t d3_service_current_buffer(void) {
    return g_current_buffer;
}

static void reply_result(Message *m, uint32_t result) {
    reply_prepare(m, 0, 1, 0);
    m->w[m->payload + 2] = result;
    reply_send(m);
}

static void reply_service_result(Message *message, uint32_t result) {
    reply_prepare(message, 0, 0, message->domain);
    message->w[message->payload + 2] = result;
    reply_send(message);
}

static int message_arguments(const Message *message, size_t bytes) {
    const size_t start = message->magic + 4u;
    return start <= message->data_end && bytes <= (message->data_end - start) * 4u;
}

static void reply_handle(Message *m, uint32_t handle) {
    reply_prepare_handle(m, 1, 1, 0, REPLY_MOVE_HANDLE);
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
    m->w[m->frame] = 1;
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

/* Set while a handler answers a command nobody implemented.  The svc dispatcher
   reads it once the handler returns and walks the guest stack then, because the
   call site's frame pointers are still live in the title's stack. */
static _Thread_local int g_trace_request;

static void reply_unsupported(const Message *m, const char *port, uint32_t command, int kind) {
    g_trace_request = 1;
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
    g_trace_request = 1;
    static unsigned missing_reports;
    if (missing_reports++ < 64)
        slog("unsupported iface=%d command=%u (%s)", iface, command, command_name(iface, command));
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
            if (clone != 0) {
                Object *parent = object_of(handle);
                Object *child = object_of(clone);
                if (parent != 0 && child != 0)
                    child->domain_key = parent->domain_key;
            }
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

/* -------------------------------------------------------------------- set  */

/* Available languages are the 18 nn::settings::Language values (0..17) of
   Horizon 10.1.0, each packed into the NUL terminated LanguageCode string.  The
   list and the count the service reports are the same length, as the guest
   caches the list then indexes it by SetLanguage. */
static const char *const g_set_languages[] = {
    "ja", "en-US", "fr", "de", "it", "es", "zh-CN", "ko", "nl",
    "pt", "ru", "zh-TW", "en-GB", "fr-CA", "es-419", "zh-Hans", "zh-Hant", "pt-BR",
};
#define D3_SET_LANGUAGE_COUNT (sizeof g_set_languages / sizeof g_set_languages[0])

static uint64_t set_language_code(size_t index) {
    uint64_t code = 0;
    for (size_t i = 0; i < 7 && g_set_languages[index][i] != 0; i++)
        code |= (uint64_t)(uint8_t)g_set_languages[index][i] << (8 * i);
    return code;
}

/* Map descriptors split the address into 32 low, 4 middle and 22 high bits. */
static uint64_t map_descriptor_size(const uint32_t *word) {
    return (uint64_t)word[0] | ((uint64_t)((word[2] >> 24) & 0xfu) << 32);
}

static uint64_t map_descriptor_address(const uint32_t *word) {
    return (uint64_t)word[1] | ((uint64_t)((word[2] >> 28) & 0xfu) << 32) |
           ((uint64_t)((word[2] >> 2) & 0x003fffffu) << 36);
}

/* Write the available LanguageCode list into the guest receive buffer.  A
   malformed or short descriptor, an out of range address, or a mapping that
   refuses the write all become a Horizon result, never a host fault. */
static uint32_t set_write_language_codes(Message *m, size_t wants) {
    const uint32_t counts = m->w[0] >> 16;
    const uint32_t send_statics = counts & 0xfu;
    const uint32_t send_buffers = (counts >> 4) & 0xfu;
    const uint32_t recv_buffers = (counts >> 8) & 0xfu;
    const uint32_t exch_buffers = (counts >> 12) & 0xfu;
    if (send_statics != 0 || send_buffers != 0 || recv_buffers != 1 || exch_buffers != 0 ||
        m->recv_buffer_count != 1 || m->recv_buffer_slot > MESSAGE_WORDS - 3u ||
        wants == 0 || wants > D3_SET_LANGUAGE_COUNT) {
        slog("set cmd=%u: expected one receive map descriptor, counts=%#x", m->command, counts);
        return D3_RESULT(120, 1);
    }
    const uint32_t *word = &m->w[m->recv_buffer_slot];
    const uint32_t mode = word[2] & 3u;
    const uint64_t size = map_descriptor_size(word);
    const uint64_t address = map_descriptor_address(word);
    const uint64_t needed = (uint64_t)wants * sizeof(uint64_t);
    if (mode == 2u || size < needed || address == 0 || address > UINTPTR_MAX - needed) {
        slog("set cmd=%u: descriptor mode=%u size=%#" PRIx64 " address=%#" PRIx64
             " too small for %#" PRIx64 " bytes", m->command, mode, size, address, needed);
        return D3_RESULT(120, 1);
    }
    uint64_t codes[D3_SET_LANGUAGE_COUNT];
    for (size_t index = 0; index < wants; index++)
        codes[index] = set_language_code(index);
    struct iovec local = { codes, (size_t)needed };
    struct iovec remote = { (void *)(uintptr_t)address, (size_t)needed };
#ifdef D3_WITH_GPU
    d3_gpu_begin_cpu_write(address, needed);
#endif
    const ssize_t wrote = process_vm_writev(getpid(), &local, 1, &remote, 1, 0);
#ifdef D3_WITH_GPU
    d3_gpu_end_cpu_write();
#endif
    if (wrote != (ssize_t)needed) {
        slog("set cmd=%u: cannot write language codes to %#" PRIx64 " errno=%d", m->command,
             address, errno);
        return D3_RESULT(120, 1);
    }
    return 0;
}

static void set_command(Message *m, uint32_t command) {
    switch (command) {
    case 0: { /* GetLanguageCode */
        const uint64_t code = set_language_code(1);
        slog("set:GetLanguageCode -> en-US");
        reply_prepare(m, 0, 2, 0);
        m->w[m->payload + 4] = (uint32_t)code;
        m->w[m->payload + 5] = (uint32_t)(code >> 32);
        reply_send(m);
        break;
    }
    case 5: { /* GetAvailableLanguageCodes2: MapAlias output, not legacy OutPointer. */
        const uint32_t result = set_write_language_codes(m, D3_SET_LANGUAGE_COUNT);
        if (result != 0) {
            reply_result(m, result);
            break;
        }
        slog("set:GetAvailableLanguageCodes2 -> %zu codes, en-US at index 1",
             (size_t)D3_SET_LANGUAGE_COUNT);
        reply_prepare(m, 0, 1, 0);
        m->w[m->payload + 4] = (uint32_t)D3_SET_LANGUAGE_COUNT;
        reply_send(m);
        break;
    }
    case 2: { /* MakeLanguageCode */
        const uint32_t language = m->w[m->magic + 4];
        if (language >= D3_SET_LANGUAGE_COUNT) {
            slog("set:MakeLanguageCode language=%u out of range -> error", language);
            reply_result(m, D3_RESULT(120, 2));
            break;
        }
        const uint64_t code = set_language_code(language);
        slog("set:MakeLanguageCode %u -> %s", language, g_set_languages[language]);
        reply_prepare(m, 0, 2, 0);
        m->w[m->payload + 4] = (uint32_t)code;
        m->w[m->payload + 5] = (uint32_t)(code >> 32);
        reply_send(m);
        break;
    }
    case 3: /* GetAvailableLanguageCodeCount */
    case 6: /* GetAvailableLanguageCodeCount2 */
        slog("set:GetAvailableLanguageCodeCount%s -> %zu", command == 6 ? "2" : "",
             (size_t)D3_SET_LANGUAGE_COUNT);
        reply_prepare(m, 0, 1, 0);
        m->w[m->payload + 4] = (uint32_t)D3_SET_LANGUAGE_COUNT;
        reply_send(m);
        break;
    case 4: /* GetRegionCode */
        slog("set:GetRegionCode -> 1 (USA)");
        reply_prepare(m, 0, 1, 0);
        m->w[m->payload + 4] = 1;
        reply_send(m);
        break;
    default:
        reply_unsupported(m, "set", command, PORT_SET);
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
    uint64_t arg; /* interface-private state (an index into g_files for IFile) */
    uint32_t pending; /* queued ReceiveMessage messages not yet consumed */
    uint32_t event;   /* ICommonStateGetter event handle handed to the guest */
    int out_of_focus_suspending; /* ISelfController::SetOutOfFocusSuspendingEnabled */
    int initialized; /* a service object the guest has been told is ready */
    uint64_t request_key;
    uint32_t inputs[4], input_count, output_storage, interactive_storage;
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

/* The library-applet-launchable event ISelfController hands out: a fake applet
   signals it again when it finishes so the engine's launch loop keeps moving. */
static uint32_t g_applet_launchable;

static uint32_t domain_add(uint32_t session, int iface) {
    for (uint32_t index = 0; index < DOMAIN_SLOTS; index++) {
        DomainObject *object = &g_domain[index];
        if (object->used)
            continue;
        object->used = 1;
        object->arg = 0;
        object->event = 0;
        object->session = d3_handle_domain_key(session);
        object->iface = iface;
        object->pending =
            iface == D3_IF_COMMON_STATE_GETTER ? D3_APPLET_MESSAGE_FOCUS_CHANGED : 0u;
        object->out_of_focus_suspending = 0;
        object->initialized = 0;
        object->request_key = 0;
        object->input_count = object->output_storage = object->interactive_storage = 0;
        return index + 1;
    }
    slog("domain table is full");
    return 0;
}

static int domain_iface(uint32_t session, uint32_t id) {
    if (id == 0 || id > DOMAIN_SLOTS)
        return D3_IF_NONE;
    DomainObject *object = &g_domain[id - 1];
    return object->used && object->session == d3_handle_domain_key(session) ? object->iface : D3_IF_NONE;
}

/* Whether the session holds any domain object at all.  ConvertCurrentObjectToDomain
   registers the session's root object, so a session without one was never
   converted and cannot be addressed by an object id. */
static int domain_any(uint32_t session) {
    const uint32_t key = d3_handle_domain_key(session);
    for (uint32_t index = 0; index < DOMAIN_SLOTS; index++) {
        if (g_domain[index].used && g_domain[index].session == key)
            return 1;
    }
    return 0;
}

static void domain_close(uint32_t session, uint32_t id) {
    if (id == 0 || id > DOMAIN_SLOTS)
        return;
    DomainObject *object = &g_domain[id - 1];
    if (object->used && object->session == d3_handle_domain_key(session)) {
        if (object->iface == D3_IF_AUDIO_OUT)
            d3_audio_close((unsigned)object->arg);
        if (object->iface == D3_IF_SAVE_FILESYSTEM)
            close((int)object->arg);
        object->used = 0;
        object->iface = D3_IF_NONE;
        object->pending = 0;
        object->out_of_focus_suspending = 0;
        object->initialized = 0;
    }
}

static void domain_close_session(uint32_t session) {
    /* Clones share one object table, so only the last handle to close drops it. */
    uint32_t key = d3_handle_domain_key(session);
    for (uint32_t index = 0; index < HANDLE_SLOTS; index++) {
        if (g_obj[index].kind != D3_OBJ_NONE && g_obj[index].domain_key == key &&
            D3_HANDLE_FIRST + index != session)
            return;
    }
    for (uint32_t id = 1; id <= DOMAIN_SLOTS; id++)
        domain_close(session, id);
}

/* Pop the oldest message queued on one domain object, or 0 when the object has
   none (or the id does not belong to this session).  Today the only queued
   message is the focus notification, so the value returned is the applet
   message kind the guest's ReceiveMessage loop is waiting for. */
static uint32_t domain_take_pending(uint32_t session, uint32_t id) {
    if (id == 0 || id > DOMAIN_SLOTS)
        return 0;
    DomainObject *object = &g_domain[id - 1];
    if (!object->used || object->session != d3_handle_domain_key(session))
        return 0;
    uint32_t message = object->pending;
    object->pending = 0;
    return message;
}

/* Remember the event handle an ICommonStateGetter handed to the guest, so the
   state change that queued a message can actually wake the guest's wait. */
static void domain_set_event(uint32_t session, uint32_t id, uint32_t event) {
    if (id == 0 || id > DOMAIN_SLOTS)
        return;
    DomainObject *object = &g_domain[id - 1];
    if (object->used && object->session == d3_handle_domain_key(session))
        object->event = event;
}

/* Signal that event when the object owes the guest a message, and clear it once
   ReceiveMessage has consumed the last one: on hardware the event is exactly
   "ReceiveMessage has something". */
static void domain_update_event(uint32_t session, uint32_t id) {
    extern void d3_event_set(uint32_t handle, int signaled);
    if (id == 0 || id > DOMAIN_SLOTS)
        return;
    DomainObject *object = &g_domain[id - 1];
    if (!object->used || object->session != d3_handle_domain_key(session) || !object->event)
        return;
    d3_event_set(object->event, object->pending != 0);
}

/* Record one ISelfController::SetOutOfFocusSuspendingEnabled value on the object
   it was sent to, so objects stay independent and the setting survives until the
   object is closed.  Out of range ids are ignored; the caller still replies. */
static void domain_set_out_of_focus_suspending(uint32_t session, uint32_t id, int enabled) {
    if (id == 0 || id > DOMAIN_SLOTS)
        return;
    DomainObject *object = &g_domain[id - 1];
    if (object->used && object->session == d3_handle_domain_key(session))
        object->out_of_focus_suspending = enabled;
}

/* Mark a pctl service object ready.  Factory command 1 (CreateServiceWithout-
   Initialize) hands out an object the guest then initializes with child command
   1; factory command 0 hands out one that is already initialized. */
static void domain_set_initialized(uint32_t session, uint32_t id, int initialized) {
    if (id == 0 || id > DOMAIN_SLOTS)
        return;
    DomainObject *object = &g_domain[id - 1];
    if (object->used && object->session == d3_handle_domain_key(session))
        object->initialized = initialized;
}

/* pctl (parental controls).  The guest boot path only needs the factory pair: on
   HOS >= 4 the client sends factory command 1 (CreateServiceWithoutInitialize)
   with a u64 pid_reserved and a matching pid, then calls the new service object's
   Initialize (child command 1).  Anything else is left to the regular
   unimplemented-command reply so a policy getter is never silently accepted. */
/* nn::aoc: the engine asks for the add-on content list while it initialises its
   content/GPU path, and nn::aoc turns a failed reply into AbortImpl("this == NULL").
   No DLC is mounted here, so every query reports an empty list. */
static void reply_handle(Message *m, uint32_t handle);
static int message_buffer(const Message *m, uint64_t *address, size_t *size);
static int message_io_buffer(const Message *message, int output, size_t wanted,
                             uint64_t *address, size_t *size);
static int guest_read(void *dst, uint64_t address, size_t size);
static int guest_write(uint64_t address, const void *src, size_t size);
static const uint64_t g_local_user[2] = {UINT64_C(0x4433484f53545531), UINT64_C(0x4c4f43414c555345)};
#define D3_IF_ACCOUNT_MANAGER 0x1000d

/* nn::account::Initialize tolerates exactly one failure code (0x2C7C, the
   "account service not initialised" result: it compares w0 & 0x3FFFFF against it)
   and aborts on anything else.  Answering every account command with that code lets
   the engine continue its start-up instead of asserting. */
static void account_command(Message *m, uint32_t command, uint32_t session) {
    /* Low frequency and on the start-up path, so every call is worth a line even
       after the general command logging has been turned off. */
    slog("account cmd=%u%s", command, m->domain ? " (domain)" : "");
    if ((command == 1 || command == 101) && !message_arguments(m, 16)) {
        reply_service_result(m, D3_RESULT(124, 20));
        return;
    }
    switch (command) {
    case 0:
        reply_prepare(m, 0, 1, m->domain);
        m->w[m->payload + 4] = 1;
        reply_send(m);
        return;
    case 1: {
        uint64_t user[2];
        memcpy(user, &m->w[m->magic + 4], sizeof user);
        reply_prepare(m, 0, 1, m->domain);
        m->w[m->payload + 4] = memcmp(user, g_local_user, sizeof user) == 0;
        reply_send(m);
        return;
    }
    case 2:
    case 3:
    case 141: {
        uint64_t address;
        size_t size;
        uint64_t users[16] = {0};
        memcpy(users, g_local_user, sizeof g_local_user);
        if (!message_io_buffer(m, 1, 0, &address, &size) || size < sizeof g_local_user ||
            size > sizeof users || !guest_write(address, users, size)) {
            reply_service_result(m, D3_RESULT(124, 20));
            return;
        }
        reply_service_result(m, 0);
        return;
    }
    case 4:
    case 51:
    case 52:
        reply_prepare(m, 0, 4, m->domain);
        memcpy(&m->w[m->payload + 4], g_local_user, sizeof g_local_user);
        reply_send(m);
        return;
    case 101: {
        uint64_t user[2];
        memcpy(user, &m->w[m->magic + 4], sizeof user);
        if (memcmp(user, g_local_user, sizeof user) != 0) {
            reply_service_result(m, D3_RESULT(124, 20));
            return;
        }
        const uint32_t object = domain_add(session, D3_IF_ACCOUNT_MANAGER);
        if (object)
            reply_domain_object(m, object);
        else
            reply_service_result(m, D3_RESULT(21, 7));
        return;
    }
    case 100: /* InitializeApplicationInfo */
    case 140: /* InitializeApplicationInfoRestricted */
    case 160: /* InitializeApplicationInfoV2 */
        /* The title owns the game, so every initialisation flavour succeeds. */
        slog("account cmd=%u (initialise application info) -> ok", command);
        reply_service_result(m, 0);
        return;
    case 50: /* IsUserRegistrationRequestPermitted: this offline host has one local user. */
    case 150: /* IsUserAccountSwitchLocked(Out<bool>) */
        /* Nothing here locks the account, and the SDK aborts on a failure. */
        slog("account cmd=%u -> false", command);
        reply_prepare(m, 0, 1, m->domain);
        m->w[m->payload + 4] = 0;
        reply_send(m);
        return;
    default:
        break;
    }
    if (g_loud < 4096) {
        g_loud++;
        slog("account cmd=%u -> 0x2C7C (not initialised)", command);
    }
    /* The engine reaches this through the converted domain object (acc:u0
       ConvertCurrentObjectToDomain -> object 14), so the reply has to use the
       domain shape; the plain form would leave the guest reading a CMIF header
       as the result code. */
    if (m->domain)
        reply_domain(m, 0x2C7Cu, 1);
    else
        reply_result(m, 0x2C7Cu);
}

/* nifm:u (IGeneralService).  The engine asks whether the console has a network
   profile before it decides which online features to use; a tablet with no
   wireless association is a normal answer (one zeroed profile), and the reply
   shapes below only have to stay well formed. */
#define D3_IF_NIFM_GENERAL 0x1000e
static uint64_t g_nifm_request_key;

static void nifm_command(Message *message, uint32_t command, uint32_t session) {
    if (command != 4 && command != 5) {
        unsupported_command(message, D3_IF_NIFM, command);
        return;
    }
    const uint32_t object = domain_add(session, D3_IF_NIFM_GENERAL);
    if (!object) {
        reply_service_result(message, D3_RESULT(21, 7));
        return;
    }
    slog("nifm CreateGeneralService -> object %u", object);
    reply_domain_object(message, object);
}

static void nifm_general_command(Message *m, uint32_t command, uint32_t session) {
    switch (command) {
    case 4: {
        if (!message_arguments(m, 4)) {
            reply_service_result(m, D3_RESULT(110, 112));
            break;
        }
        const uint32_t object = domain_add(session, D3_IF_NIFM_REQUEST);
        if (!object) {
            reply_service_result(m, D3_RESULT(21, 7));
            break;
        }
        g_domain[object - 1].arg = 1;
        g_domain[object - 1].event = 0;
        g_domain[object - 1].request_key = ++g_nifm_request_key;
        g_domain[object - 1].pending = 0;
        slog("nifm CreateRequest -> object %u (offline)", object);
        reply_domain_object(m, object);
        break;
    }
    case 1: /* GetClientId(Out<u64>) */
        reply_prepare(m, 0, 2, m->domain);
        m->w[m->payload + 4] = 1; /* the SDK rejects a zero client id */
        m->w[m->payload + 5] = 0;
        reply_send(m);
        break;
    case 12:
    case 17:
    case 21:
    case 22:
        reply_prepare(m, 0, 1, m->domain);
        m->w[m->payload + 4] = 0;
        slog("nifm general cmd=%u -> offline", command);
        reply_send(m);
        break;
    default:
        unsupported_command(m, D3_IF_NIFM, command);
        break;
    }
}

static void nifm_request_command(Message *message, uint32_t command) {
    DomainObject *object = &g_domain[message->domain_object - 1];
    extern void d3_event_set(uint32_t handle, int signaled);
    if (g_nifm_poll_logs < 32) {
        g_nifm_poll_logs++;
        slog("nifm request cmd=%u state=%" PRIu64, command, object->arg);
    }
    switch (command) {
    case 0:
        reply_prepare(message, 0, 1, message->domain);
        message->w[message->payload + 4] = (uint32_t)object->arg;
        reply_send(message);
        break;
    case 1:
        reply_service_result(message, D3_RESULT(110, 1111));
        break;
    case 2: {
        const uint32_t state_event = d3_handle_alloc(D3_OBJ_EVENT, "nifm-state", object->request_key);
        const uint32_t change_event = d3_handle_alloc(D3_OBJ_EVENT, "nifm-change", object->request_key);
        if (!state_event || !change_event) {
            if (state_event)
                d3_handle_close(state_event);
            if (change_event)
                d3_handle_close(change_event);
            reply_service_result(message, D3_RESULT(21, 7));
            break;
        }
        if (object->pending)
            d3_event_set(state_event, 1);
        reply_prepare_handle(message, 2, 0, message->domain, REPLY_COPY_HANDLE);
        message->w[message->handle_slot_out] = state_event;
        message->w[message->handle_slot_out + 1] = change_event;
        reply_send(message);
        break;
    }
    case 3:
    case 4:
        object->arg = 1;
        object->pending = 1;
        for (uint32_t index = 0; index < HANDLE_SLOTS; index++) {
            if (g_obj[index].kind == D3_OBJ_EVENT && g_obj[index].arg == object->request_key &&
                strcmp(g_obj[index].name, "nifm-state") == 0)
                d3_event_set(D3_HANDLE_FIRST + index, 1);
        }
        reply_service_result(message, 0);
        break;
    case 6:
    case 11:
        if (!message_arguments(message, 4)) {
            reply_service_result(message, D3_RESULT(110, 112));
            break;
        }
        if (command == 6)
            object->initialized = (int)message->w[message->magic + 4];
        else
            object->out_of_focus_suspending = message->w[message->magic + 4] != 0;
        reply_service_result(message, 0);
        break;
    default:
        unsupported_command(message, D3_IF_NIFM_REQUEST, command);
        break;
    }
}

static uint32_t g_apm_configurations[2] = {0x20003, 0x20003};

static void nfp_manager_command(Message *message, uint32_t command, uint32_t session) {
    if (command != 0 || !message->domain) {
        unsupported_command(message, D3_IF_NFP_MANAGER, command);
        return;
    }
    const uint32_t object = domain_add(session, D3_IF_NFP_USER);
    if (!object) {
        reply_service_result(message, D3_RESULT(21, 7));
        return;
    }
    slog("nfp CreateUserInterface -> object %u (no NFC devices)", object);
    reply_domain_object(message, object);
}

static void nfp_user_command(Message *message) {
    DomainObject *object = &g_domain[message->domain_object - 1];
    switch (message->command) {
    case 0:
        object->initialized = 1;
        slog("nfp Initialize -> initialized without NFC devices");
        reply_service_result(message, 0);
        break;
    case 1:
        object->initialized = 0;
        reply_service_result(message, 0);
        break;
    case 2: {
        uint64_t address;
        size_t size;
        if (!object->initialized) {
            reply_service_result(message, D3_RESULT(115, 77));
            break;
        }
        if (!message_io_buffer(message, 1, 0, &address, &size) || size < 8) {
            reply_service_result(message, D3_RESULT(115, 65));
            break;
        }
        reply_prepare(message, 0, 1, message->domain);
        message->w[message->payload + 4] = 0;
        reply_send(message);
        break;
    }
    case 19:
        reply_prepare(message, 0, 1, message->domain);
        message->w[message->payload + 4] = object->initialized != 0;
        reply_send(message);
        break;
    case 23: {
        const uint32_t event = d3_handle_alloc(D3_OBJ_EVENT, "nfp-availability", 0);
        if (event)
            reply_domain_handle(message, event);
        else
            reply_service_result(message, D3_RESULT(21, 7));
        break;
    }
    default:
        unsupported_command(message, D3_IF_NFP_USER, message->command);
        break;
    }
}

static void apm_command(Message *message, uint32_t command, uint32_t session) {
    if (command == 0) {
        if (message->domain) {
            const uint32_t object = domain_add(session, D3_IF_APM_SESSION);
            if (object)
                reply_domain_object(message, object);
            else
                reply_service_result(message, D3_RESULT(21, 7));
        } else {
            const uint32_t handle = d3_handle_alloc(D3_OBJ_SESSION, "apm-session", PORT_APM_SESSION);
            if (handle)
                reply_handle(message, handle);
            else
                reply_service_result(message, D3_RESULT(21, 7));
        }
        slog("apm OpenSession");
    } else if (command == 1 || command == 6) {
        reply_prepare(message, 0, 1, message->domain);
        message->w[message->payload + 4] = 0;
        reply_send(message);
    } else {
        unsupported_command(message, D3_IF_APM, command);
    }
}

static void apm_session_command(Message *message, uint32_t command) {
    if ((command != 0 && command != 1) || !message_arguments(message, command == 0 ? 8 : 4)) {
        unsupported_command(message, D3_IF_APM_SESSION, command);
        return;
    }
    const uint32_t mode = message->w[message->magic + 4];
    if (mode > 1) {
        reply_service_result(message, D3_RESULT(128, 1));
        return;
    }
    if (command == 0) {
        g_apm_configurations[mode] = message->w[message->magic + 5];
        slog("apm requested performance mode=%u config=%#x", mode, g_apm_configurations[mode]);
        reply_service_result(message, 0);
    } else {
        reply_prepare(message, 0, 1, message->domain);
        message->w[message->payload + 4] = g_apm_configurations[mode];
        reply_send(message);
    }
}

static void aoc_command(Message *m, uint32_t command, uint32_t session) {
    static unsigned log_count;
    const int log_request = log_count++ < 16;
    (void)session;
    switch (command) {
    case 0:
    case 2: {
        unsigned ids[64];
        const size_t count = d3_content_addon_ids(ids, 64);
        if (log_request) slog("aoc::CountAddOnContent -> %zu", count);
        reply_prepare(m, 0, 1, m->domain);
        m->w[m->payload + 4] = (uint32_t)count;
        reply_send(m);
        break;
    }
    case 1:
    case 3: {
        unsigned ids[64];
        const size_t installed = d3_content_addon_ids(ids, 64);
        const uint32_t offset = m->w[m->magic + 4], capacity = m->w[m->magic + 5];
        if (installed && (!message_arguments(m, 8) || offset > installed)) {
            reply_service_result(m, D3_RESULT(128, 2)); break;
        }
        size_t count = offset < installed ? installed - offset : 0;
        if (count > capacity) count = capacity;
        uint64_t address; size_t bytes;
        if (count && (!message_io_buffer(m, 1, 0, &address, &bytes) ||
                      count > bytes / sizeof(unsigned) || !guest_write(address, ids + offset, count * sizeof(unsigned)))) {
            reply_service_result(m, D3_RESULT(2, 120)); break;
        }
        if (log_request) slog("aoc::ListAddOnContent -> %zu entries", count);
        reply_prepare(m, 0, 1, m->domain);
        m->w[m->payload + 4] = (uint32_t)count;
        reply_send(m);
        break;
    }
    case 6:
    case 7: {
        char root[512];
        const unsigned index = m->w[m->magic + 4];
        reply_service_result(m, message_arguments(m, 4) && d3_content_addon_root(index, root, sizeof root)
                                  ? 0 : D3_RESULT(2, 1002));
        break;
    }
    case 4:
    case 5: {
        const uint64_t base_id = 0x01001b300b9bf000ull;
        reply_prepare(m, 0, 2, m->domain);
        memcpy(&m->w[m->payload + 4], &base_id, sizeof base_id);
        reply_send(m);
        break;
    }
    case 8:
    case 10: {
        uint32_t event = d3_handle_alloc(D3_OBJ_EVENT, "aoc-event", 0);
        if (log_request) slog("aoc::GetAddOnContentListChangedEvent -> %#x", event);
        if (event == 0) {
            reply_result(m, D3_RESULT(21, 7));
            break;
        }
        reply_prepare_handle(m, 1, 0, m->domain, REPLY_COPY_HANDLE);
        m->w[m->handle_slot_out] = event;
        reply_send(m);
        break;
    }
    default:
        reply_unsupported(m, "aoc:u", command, PORT_AOC);
        break;
    }
}

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
        g_domain[object - 1].arg = 0;
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
    case 1001:
        g_domain[m->domain_object - 1].arg = 1;
        slog("IParentalControlService::CheckFreeCommunicationPermission -> unrestricted local policy");
        reply_service_result(m, 0);
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
static void application_pop_launch_parameter(Message *message, uint32_t session);

static void application_functions_command(Message *m, uint32_t command, uint32_t session) {
    switch (command) {
    case 20: { /* EnsureSaveData for the local user's account storage. */
        uint64_t user[2];
        if (!message_arguments(m, sizeof user)) { reply_service_result(m, D3_RESULT(2, 1)); break; }
        memcpy(user, &m->w[m->magic + 4], sizeof user);
        if (memcmp(user, g_local_user, sizeof user) != 0) { reply_service_result(m, D3_RESULT(124, 20)); break; }
        char directory[512];
        snprintf(directory, sizeof directory, "%s/saves", D3_DATA_ROOT);
        uint32_t result = 0;
        if (mkdir(directory, 0700) != 0 && errno != EEXIST) result = D3_RESULT(2, 1002);
        snprintf(directory, sizeof directory,
                "%s/saves/1-%016" PRIx64 "-%016" PRIx64 "-%016" PRIx64 "-%016" PRIx64 "-%08x",
                D3_DATA_ROOT, UINT64_C(0), user[0], user[1], UINT64_C(0), 1u);
        if (!result && mkdir(directory, 0700) != 0 && errno != EEXIST) result = D3_RESULT(2, 1002);
        slog("EnsureSaveData directory=%s result=%#x", directory, result);
        reply_prepare(m, 0, 2, m->domain);
        m->w[m->payload + 2] = result;
        reply_send(m);
        break;
    }
    case 1: /* PopLaunchParameter (Out<SharedPointer<IStorage>>, LaunchParameterKind) */
        application_pop_launch_parameter(m, session);
        break;
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
    case 40: {
        DomainObject *object = &g_domain[m->domain_object - 1];
        const uint32_t became_running = !object->initialized;
        object->initialized = 1;
        slog("IApplicationFunctions::NotifyRunning -> running (transition=%u)", became_running);
        reply_prepare(m, 0, 1, m->domain);
        m->w[m->payload + 4] = became_running;
        reply_send(m);
        break;
    }
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
        if (event == 0) {
            reply_domain(m, D3_RESULT(21, 7), 1);
        } else {
            domain_set_event(session, m->domain_object, event);
            domain_update_event(session, m->domain_object);
            reply_domain_handle(m, event);
        }
        break;
    }
    case 1: { /* ReceiveMessage (Out<AppletMessage>) */
        uint32_t message = domain_take_pending(session, m->domain_object);
        domain_update_event(session, m->domain_object);
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
    case 0x42: /* SetCpuBoostMode(int): a clock hint the host has no use for. */
        slog("ICommonStateGetter::SetCpuBoostMode(%d) -> ok", (int)m->w[m->magic + 4]);
        reply_domain(m, 0, 1);
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
        extern void d3_event_set(uint32_t handle, int signaled);
        uint32_t event = d3_handle_alloc(D3_OBJ_EVENT, "applet-launchable", 0);
        slog("ISelfController::GetLibraryAppletLaunchableEvent -> handle %#x", event);
        if (event == 0) {            reply_domain(m, D3_RESULT(21, 7), 1);
        } else {
            /* Signalled straight away: on hardware this event means "a library
               applet may be launched now", which is true for a focused
               application.  Left unsignalled it wedged the boot: the engine's
               applet worker waits on it while holding a lock the main thread
               then blocks on (probe logcat-baseline-r37: "sync: lock
               0x552a000048 tag=1 owner=4114 blocks" is the last main-thread
               line), so nothing after nvdrv::Open ever ran. */
            d3_event_set(event, 1);
            /* Level triggered: "a library applet may be launched" stays true, so
               every wait returns instead of consuming the one signal. */
            d3_handle_set_arg(event, 1);
            g_applet_launchable = event;
            reply_domain_handle(m, event);
        }
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

/* [6.0.0+] The service owns one 0x1000 byte shared memory (steady clock time
   points and system clock contexts) and hands callers a native handle to it.
   libnx maps exactly this size (nx/source/services/time.c), and the SDK asks for
   the handle with command 20. */
#define D3_TIME_SHARED_MEMORY_BYTES 0x1000u

static void time_service_command(Message *m, uint32_t command, uint32_t session) {
    switch (command) {
    case 3:
        if (m->domain) {
            uint32_t object = domain_add(session, D3_IF_TIME_ZONE);
            slog("ITimeService::GetTimeZoneService -> object %u", object);
            if (object == 0)
                reply_domain(m, D3_RESULT(21, 7), 1);
            else
                reply_domain_object(m, object);
            return;
        }
        {
            uint32_t handle = d3_handle_alloc(D3_OBJ_SESSION, "ITimeZoneService", PORT_TIME_ZONE);
            slog("ITimeService::GetTimeZoneService -> session %#x", handle);
            if (handle == 0) {
                reply_result(m, D3_RESULT(21, 7));
                return;
            }
            reply_prepare_handle(m, 1, 0, 0, REPLY_MOVE_HANDLE);
            m->w[m->handle_slot_out] = handle;
            reply_send(m);
        }
        return;
    case 20: {
        /* GetSharedMemory: a native handle to the read-only time block, which the
           caller maps with MapSharedMemory.  The block is not backed by a real
           clock yet, so the caller reads zeros (the epoch plus its own steady
           tick); the handle is what carries the SDK's time init past this point.
           An out handle is never a domain object, so a domain session still puts
           it in the HIPC slot. */
        uint32_t handle = d3_handle_alloc(D3_OBJ_SHARED_MEM, "time-shmem",
                                          D3_TIME_SHARED_MEMORY_BYTES);
        slog("ITimeService::GetSharedMemory -> handle %#x", handle);
        if (handle == 0) {
            if (m->domain)
                reply_domain(m, D3_RESULT(21, 7), 1);
            else
                reply_result(m, D3_RESULT(21, 7));
            return;
        }
        if (m->domain) {
            reply_domain_handle(m, handle);
        } else {
            reply_prepare_handle(m, 1, 0, 0, REPLY_MOVE_HANDLE);
            m->w[m->handle_slot_out] = handle;
            reply_send(m);
        }
        return;
    }
    default:
        unsupported_command(m, D3_IF_TIME, command);
        return;
    }
}

/* fssrv::sf::IFileSystem.  Command 1 is OpenFile, which carries a path such as
   "data:/CPKs/Common.cpk"; the rest are scalar queries.  Files are addressed by
   object id afterwards, so IFile gets its own interface tag. */

/* IFile is addressed by object id once OpenFile hands one out, so it needs its
   own interface tag.  The data itself lives on the host: paths arrive as
   "data:/..." and resolve under D3_DATA_ROOT/romfs. */
#define D3_IF_FILE 0x10002

typedef struct {
    int used;
    int fd;
    uint64_t size;
    uint64_t offset;
} HostFile;

static HostFile g_files[32];

/* Game data cannot live in the APK (13 GB of CPKs), so it is staged on the
   device and the first readable copy wins.  /data/local/tmp is the only place
   adb can push to that the app may also read. */
static const char *const g_romfs_roots[] = {
    "/data/local/tmp/d3romfs",
    D3_DATA_ROOT "/romfs",
};

static int host_file_open(const char *path) {
    char host[512];
    const char *name = path;
    int fd = -1;
    if (strncmp(name, "data:", 5) == 0)
        name += 5;
    while (*name == '/')
        name++;
    if (*name == 0)
        return -1;
    for (size_t root = 0; root < sizeof g_romfs_roots / sizeof g_romfs_roots[0]; root++) {
        snprintf(host, sizeof host, "%s/%s", g_romfs_roots[root], name);
        fd = open(host, O_RDONLY);
        if (fd >= 0)
            break;
    }
    if (fd < 0) {
        slog("fs: open %s failed errno %d", name, errno);
        return -1;
    }
    for (int index = 0; index < (int)(sizeof g_files / sizeof g_files[0]); index++) {
        if (g_files[index].used)
            continue;
        struct stat info;
        if (fstat(fd, &info) != 0) {
            close(fd);
            return -1;
        }
        g_files[index].used = 1;
        g_files[index].fd = fd;
        g_files[index].size = (uint64_t)info.st_size;
        g_files[index].offset = 0;
        slog("fs: opened %s (%llu bytes)", host, (unsigned long long)info.st_size);
        return index;
    }
    close(fd);
    return -1;
}

/* Extract the first path-looking printable run from a request buffer. */
static int message_path(const Message *m, char *out, size_t size) {
    const unsigned char *bytes = (const unsigned char *)m->w;
    char run[256];
    size_t used = 0;
    for (size_t index = 0; index < 0x1000; index++) {
        unsigned char byte = bytes[index];
        if (byte >= 0x20 && byte < 0x7f) {
            if (used < sizeof run - 1)
                run[used++] = (char)byte;
        } else {
            run[used] = 0;
            if (used >= 6 && strchr(run, ':') != 0 && strchr(run, '/') != 0 &&
                strncmp(run, "SFCI", 4) != 0 && strncmp(run, "SFCO", 4) != 0) {
                snprintf(out, size, "%s", run);
                return 0;
            }
            used = 0;
        }
    }
    return -1;
}

static uint32_t g_fs_access_log_mode;
static int g_fs_auto_create = 1;
static int message_buffer(const Message *m, uint64_t *address, size_t *size);
static int guest_read(void *dst, uint64_t address, size_t size);

static uint32_t save_filesystem_open(Message *message, uint32_t session) {
    const size_t start = message->magic + 6u;
    if (!message_arguments(message, 72))
        return D3_RESULT(2, 1);
    uint64_t attributes[8];
    memcpy(attributes, &message->w[start], sizeof attributes);
    const uint32_t space = message->w[message->magic + 4u] & 0xffu;
    const uint8_t type = (uint8_t)attributes[4];
    const int automatic = g_fs_auto_create &&
        (type == 4 || type == 5 || (space == 1 && (type == 1 || type == 3) &&
                                  attributes[0] == 0 && attributes[3] == 0));
    char directory[512];
    const int length = snprintf(directory, sizeof directory,
                                "%s/saves/%u-%016" PRIx64 "-%016" PRIx64 "-%016" PRIx64
                                "-%016" PRIx64 "-%08" PRIx32,
                                D3_DATA_ROOT, space, attributes[0], attributes[1], attributes[2],
                                attributes[3], (uint32_t)attributes[4]);
    if (length < 0 || (size_t)length >= sizeof directory)
        return D3_RESULT(2, 1);
    if (automatic) {
        char parent[512];
        snprintf(parent, sizeof parent, "%s/saves", D3_DATA_ROOT);
        if (mkdir(parent, 0700) != 0 && errno != EEXIST)
            return D3_RESULT(2, 1002);
        if (mkdir(directory, 0700) != 0 && errno != EEXIST)
            return D3_RESULT(2, 1002);
    }
    const int descriptor = open(directory, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (descriptor < 0)
        return D3_RESULT(2, 1002);
    const uint32_t object = domain_add(session, D3_IF_SAVE_FILESYSTEM);
    if (object == 0) {
        close(descriptor);
        return D3_RESULT(21, 7);
    }
    g_domain[object - 1].arg = (uint64_t)descriptor;
    slog("fsp-srv OpenSaveDataFileSystem space=%u type=%u auto=%d directory=%s -> object %u",
         space, type, automatic, directory, object);
    reply_domain_object(message, object);
    return 0;
}

#include "d3_save_ops.inc"

static void save_filesystem_command(Message *message, uint32_t command) {
    const int root = (int)g_domain[message->domain_object - 1u].arg;
    if (command <= 3 || command == 5 || command == 6) {
        reply_service_result(message, save_mutate(message, root, command));
        return;
    }
    if (command == 10) {
        const uint32_t result = fsync(root) == 0 ? 0 : D3_RESULT(2, 1002);
        reply_domain(message, result, 0);
        return;
    }
    if (command == 11 || command == 12) {
        struct statvfs space;
        if (fstatvfs(root, &space) != 0) {
            reply_domain(message, D3_RESULT(2, 1002), 0);
            return;
        }
        const uint64_t bytes = (uint64_t)(command == 11 ? space.f_bavail : space.f_blocks) *
                               space.f_frsize;
        reply_prepare(message, 0, 2, 1);
        memcpy(&message->w[message->payload + 4], &bytes, sizeof bytes);
        reply_send(message);
        return;
    }
    if (command == 7) {
        uint64_t address = 0;
        size_t size = 0;
        char path[0x301];
        if (!message_buffer(message, &address, &size) || size > sizeof path || size == 0 ||
            !guest_read(path, address, size) || memchr(path, 0, size) == NULL) {
            reply_domain(message, D3_RESULT(2, 1), 0);
            return;
        }
        char *name = path;
        while (*name == '/')
            name++;
        int parent = dup(root);
        if (parent < 0) {
            reply_domain(message, D3_RESULT(2, 1002), 0);
            return;
        }
        uint32_t result = 0;
        struct stat entry;
        char *part = name;
        for (;;) {
            char *separator = strchr(part, '/');
            if (separator)
                *separator = 0;
            if (strcmp(part, "..") == 0 || strchr(part, '\\') != NULL) {
                result = D3_RESULT(2, 1);
                break;
            }
            if (!separator) {
                if (fstatat(parent, *part ? part : ".", &entry, AT_SYMLINK_NOFOLLOW) != 0 ||
                    (!S_ISREG(entry.st_mode) && !S_ISDIR(entry.st_mode)))
                    result = D3_RESULT(2, 1);
                break;
            }
            const int next = openat(parent, *part ? part : ".",
                                    O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
            if (next < 0) {
                result = D3_RESULT(2, 1);
                break;
            }
            close(parent);
            parent = next;
            part = separator + 1;
        }
        close(parent);
        reply_prepare(message, 0, result ? 0 : 1, 1);
        message->w[message->payload + 2] = result;
        if (result == 0)
            message->w[message->payload + 4] = S_ISDIR(entry.st_mode) ? 0 : 1;
        reply_send(message);
        return;
    }
    unsupported_command(message, D3_IF_SAVE_FILESYSTEM, command);
}

static void fsp_srv_command(Message *m, uint32_t command, uint32_t session) {
    slog("fsp-srv command %u", command);
    switch (command) {
    case 51: {
        const uint32_t result = save_filesystem_open(m, session);
        if (result != 0)
            reply_domain(m, result, 0);
        break;
    }
    case 1003:
        g_fs_auto_create = 0;
        reply_domain(m, 0, 0);
        break;
    case 1004:
        g_fs_access_log_mode = m->w[m->magic + 4];
        reply_domain(m, 0, 0);
        break;
    case 1: { /* OpenFile(path, mode) -> an IFile domain object */
        char path[256];
        int file = message_path(m, path, sizeof path) == 0 ? host_file_open(path) : -1;
        if (file < 0) {
            reply_domain(m, 0x7D402u, 1);
            break;
        }
        uint32_t object = domain_add(session, D3_IF_FILE);
        if (object == 0) {
            close(g_files[file].fd);
            g_files[file].used = 0;
            reply_domain(m, D3_RESULT(21, 7), 1);
            break;
        }
        g_domain[object - 1].arg = (uint64_t)file;
        slog("fsp-srv OpenFile -> object %u", object);
        reply_domain_object(m, object);
        break;
    }
    case 1005:
        reply_prepare(m, 0, 1, 1);
        m->w[m->payload + 4] = g_fs_access_log_mode;
        slog("fsp-srv GetGlobalAccessLogMode -> None");
        reply_send(m);
        break;
    case 1011:
        reply_prepare(m, 0, 2, 1);
        m->w[m->payload + 4] = 2;
        m->w[m->payload + 5] = 0;
        reply_send(m);
        break;
    default:
        /* The IFileSystem command set is not recovered yet.  A success reply
           without the out object nn::fs expects only reaches an assertion, so
           answer with a real fs result instead: MAKERESULT(2, 1002) is what the
           SDK itself checks for "path not found", which callers can handle. */
        slog("fsp-srv cmd=%u -> fs not-found", command);
        reply_domain(m, 0x7D402u, 1);
        break;
    }
}

static void file_command(Message *m, uint32_t command, uint32_t session) {
    (void)session;
    int index = -1;
    if (m->domain_object >= 1 && m->domain_object <= DOMAIN_SLOTS) {
        DomainObject *object = &g_domain[m->domain_object - 1];
        if (object->used && object->iface == D3_IF_FILE)
            index = (int)object->arg;
    }
    if (index < 0 || index >= (int)(sizeof g_files / sizeof g_files[0])) {
        unsupported_command(m, D3_IF_FILE, command);
        return;
    }
    HostFile *file = &g_files[index];
    switch (command) {
    case 0: /* Read: no data served yet, report end of file */
        slog("IFile::Read -> 0");
        reply_prepare(m, 0, 2, 1);
        m->w[m->payload + 4] = 0;
        reply_send(m);
        break;
    case 2: /* Flush */
    case 3: /* SetSize */
        slog("IFile cmd %u -> ok", command);
        reply_domain(m, 0, 1);
        break;
    case 4: /* GetSize */
        slog("IFile::GetSize -> %llu", (unsigned long long)file->size);
        reply_prepare(m, 0, 4, 1);
        memcpy(&m->w[m->payload + 4], &file->size, sizeof file->size);
        reply_send(m);
        break;
    default:
        unsupported_command(m, D3_IF_FILE, command);
        break;
    }
}

/* nv::nvdrv::INvDrvServices (the private "nvdrv" port).  Device fds are only
   bookkeeping for now: the ioctls that would configure a channel are accepted
   so the SDK can finish graphics initialisation and reveal what it asks for. */
static uint32_t g_nvdrv_ioctls;

/* A service command may arrive on a plain session or on a domain object; the
   reply shape differs, so route through one helper. */
static void reply_ok(Message *m, uint32_t params) {
    reply_prepare(m, 0, params, m->domain);
    reply_send(m);
}

static void nvdrv_command(Message *m, uint32_t command, uint32_t session) {
    switch (command) {
    case 0: { /* Open(path, Out<fd>) */
        uint64_t address;
        size_t size;
        char path[64] = {0};
        uint32_t fd = UINT32_MAX;
        uint32_t result = 4;
        if (message_io_buffer(m, 0, 0, &address, &size) && size < sizeof path &&
            guest_read(path, address, size))
            result = d3_nv_open(d3_handle_domain_key(session), path, &fd);
        slog("nvdrv::Open %s -> fd %u result=%#x", path, fd, result);
        reply_prepare(m, 0, 2, m->domain);
        m->w[m->payload + 4] = fd;
        m->w[m->payload + 5] = result;
        reply_send(m);
        break;
    }
    case 1: /* Ioctl */
    case 11: /* Ioctl2 */
    case 12: { /* Ioctl3 */
        /* The ioctl arguments are what the GPU bring-up has to answer, so every
           call reports the command, the fd and the whole raw payload (buffer
           descriptors included) until the set of commands is known. */
        if (g_nvdrv_ioctls < 80) {
            g_nvdrv_ioctls++;
            slog("nvdrv::Ioctl#%u cmd=%#x fd=%u args=%#x %#x %#x %#x %#x %#x %#x %#x %#x",
                 g_nvdrv_ioctls, m->w[m->magic + 5], m->w[m->magic + 4], m->w[m->magic + 6],
                 m->w[m->magic + 7], m->w[m->magic + 8], m->w[m->magic + 9],
                 m->w[m->magic + 10], m->w[m->magic + 11], m->w[m->magic + 12],
                 m->w[m->magic + 13], m->w[m->magic + 14]);
        }
        const uint32_t descriptor = m->w[m->magic + 4];
        const uint32_t ioctl = m->w[m->magic + 5];
        const size_t length = (ioctl >> 16u) & 0x3fffu;
        uint32_t parameters[4096] = {0};
        uint32_t inline_output[4096] __attribute__((aligned(16))) = {0};
        uint64_t input_address = 0, output_address = 0, inline_address = 0;
        size_t input_size = 0, output_size = 0, inline_size = 0;
        message_io_buffer(m, 0, 0, &input_address, &input_size);
        message_io_buffer(m, 1, 0, &output_address, &output_size);
        if (command == 12)
            message_io_buffer(m, 1, 1, &inline_address, &inline_size);
        if (command == 11)
            message_io_buffer(m, 0, 1, &inline_address, &inline_size);
        uint32_t result = 10;
        if (length <= sizeof parameters && inline_size <= sizeof inline_output &&
            (!(ioctl & 0x40000000u) || (input_size >= length &&
              guest_read(parameters, input_address, length))) &&
            (!(ioctl & 0x80000000u) || output_size >= length)) {
            if (command == 11 && ioctl == 0xc018481bu) {
                if (length == 24 && guest_read(inline_output, inline_address, inline_size))
                    result = d3_nv_submit(d3_handle_domain_key(session), descriptor, parameters,
                                          (const uint64_t *)inline_output, inline_size);
            } else {
                result = d3_nv_ioctl(d3_handle_domain_key(session), descriptor, ioctl,
                                     parameters, length, inline_output, inline_size);
            }
            if (ioctl == 0xc0200104u)
                slog("nvmap alloc handle=%#x heap=%#x flags=%#x align=%#x kind=%#x address=%#x%08x",
                     parameters[0], parameters[1], parameters[2], parameters[3], parameters[4],
                     parameters[7], parameters[6]);
            if (!result && (ioctl & 0x80000000u) &&
                (!guest_write(output_address, parameters, length) ||
                 (command == 12 && inline_size && !guest_write(inline_address, inline_output, inline_size))))
                result = 9;
        }
        if (result || g_nvdrv_ioctls++ < 32) slog("nvdrv ioctl=%#x fd=%u in=%zu out=%zu inline=%zu -> %#x", ioctl, descriptor,
             input_size, output_size, inline_size, result);
        if (result)
            slog("nvdrv failure words=%#x %#x %#x %#x %#x %#x %#x %#x", parameters[0], parameters[1],
                 parameters[2], parameters[3], parameters[4], parameters[5], parameters[6], parameters[7]);
        reply_prepare(m, 0, 1, m->domain);
        m->w[m->payload + 4] = result;
        reply_send(m);
        break;
    }
    case 2: { /* Close */
        const uint32_t result = d3_nv_close(d3_handle_domain_key(session), m->w[m->magic + 4]);
        reply_prepare(m, 0, 1, m->domain);
        m->w[m->payload + 4] = result;
        reply_send(m);
        break;
    }
    case 3: /* Initialize */
        slog("nvdrv::Initialize -> ok");
        reply_ok(m, 1);
        break;
    case 4: { /* QueryEvent(fd, Out<event handle>) */
        uint32_t event = d3_handle_alloc(D3_OBJ_EVENT, "nvdrv-event", 0);
        slog("nvdrv::QueryEvent -> handle %#x", event);
        if (event == 0)
            reply_domain(m, D3_RESULT(21, 7), 1);
        else
            reply_domain_handle(m, event);
        break;
    }
    case 13: /* SetConfiguration(u64) */
        slog("nvdrv::SetConfiguration %#x", m->w[m->magic + 4]);
        reply_ok(m, 1);
        break;
    default:
        slog("nvdrv cmd=%u -> ok (stub)", command);
        reply_ok(m, 1);
        break;
    }
}

/* vi:m / vi:s / vi:u are the display manager; GetDisplayService hands back an
   IApplicationDisplayService object.  The display path itself is not modelled
   yet, so the application object answers with zeroed results and logs what the
   title asks for. */
static void reply_u64(Message *m, uint64_t value) {
    reply_prepare(m, 0, 4, m->domain ? 1 : 0);
    memcpy(&m->w[m->payload + 4], &value, sizeof value);
    reply_send(m);
}

static pthread_mutex_t g_vi_mutex = PTHREAD_MUTEX_INITIALIZER;
static int64_t g_vi_refs[2];
static uint32_t g_vi_api;
static uint32_t g_vi_buffer_count = 3;
static uint32_t g_vi_width = 1280;
static uint32_t g_vi_height = 720;
static uint32_t g_vi_format = 1;

typedef struct {
    uint32_t data[91];
    uint64_t address;
    uint64_t size;
    int populated;
    int dequeued;
    int requested;
} ViBuffer;

static ViBuffer g_vi_buffers[64];

static void vi_release_buffer(ViBuffer *buffer) {
    if (buffer->populated) {
#ifdef D3_WITH_GPU
        d3_gpu_release_framebuffer(buffer->address, buffer->size);
#endif
        d3_nv_buffer_unpin(buffer->data[11]);
    }
    memset(buffer, 0, sizeof *buffer);
}

static void vi_update_events(void) {
    extern void d3_event_set(uint32_t handle, int signaled);
    int available = 0;
    for (size_t index = 0; index < g_vi_buffer_count; index++)
        available |= g_vi_buffers[index].populated && !g_vi_buffers[index].dequeued;
    for (size_t index = 0; index < HANDLE_SLOTS; index++) {
        if (g_obj[index].kind == D3_OBJ_EVENT &&
            strcmp(g_obj[index].name, "vi-buffer-available") == 0)
            d3_event_set(D3_HANDLE_FIRST + (uint32_t)index, available);
    }
}

static void binder_command(Message *message, uint32_t command) {
    if (!message_arguments(message, command == 1 ? 12 : 8) ||
        message->w[message->magic + 4] != 1) {
        reply_result(message, D3_RESULT(114, 1));
        return;
    }
    const uint32_t *arguments = &message->w[message->magic + 4];
    if (command == 1) {
        const int32_t change = (int32_t)arguments[1];
        const uint32_t type = arguments[2];
        pthread_mutex_lock(&g_vi_mutex);
        const int valid = type < 2 && g_vi_refs[type] + change >= 0 &&
                          g_vi_refs[type] + change <= INT32_MAX;
        if (valid)
            g_vi_refs[type] += change;
        pthread_mutex_unlock(&g_vi_mutex);
        if (valid)
            reply_ok(message, 0);
        else
            reply_result(message, D3_RESULT(114, 1));
        return;
    }
    if (command == 2) {
        if (arguments[1] != 0xf) {
            reply_result(message, D3_RESULT(114, 1));
            return;
        }
        const uint32_t event = d3_handle_alloc(D3_OBJ_EVENT, "vi-buffer-available", 1);
        if (!event) {
            reply_result(message, D3_RESULT(21, 7));
            return;
        }
        pthread_mutex_lock(&g_vi_mutex);
        vi_update_events();
        pthread_mutex_unlock(&g_vi_mutex);
        reply_prepare_handle(message, 1, 0, 0, REPLY_COPY_HANDLE);
        message->w[message->handle_slot_out] = event;
        reply_send(message);
        return;
    }
    if (command != 0 && command != 3) {
        reply_result(message, D3_RESULT(120, 1));
        return;
    }
    uint64_t input = 0, output = 0;
    size_t input_size = 0, output_size = 0;
    const uint32_t transaction = arguments[1];
    if (!message_arguments(message, 12) ||
        !message_io_buffer(message, 0, 0, &input, &input_size) || input_size < 24 ||
        !message_io_buffer(message, 1, 0, &output, &output_size) || output_size < 20) {
        reply_result(message, D3_RESULT(114, 1));
        return;
    }
    const uint32_t *parcel = (const uint32_t *)(uintptr_t)input;
    const uint64_t data_offset = parcel[1], data_size = parcel[0];
    if ((data_offset & 3u) || data_offset > input_size || data_size > input_size - data_offset ||
        data_size < 8) {
        reply_result(message, D3_RESULT(114, 1));
        return;
    }
    const uint32_t *data = (const uint32_t *)((uintptr_t)input + data_offset);
    const uint64_t token_bytes = ((uint64_t)data[1] + 1u) * 2u;
    const uint64_t argument_offset = (8u + token_bytes + 3u) & ~3ull;
    if (argument_offset > data_size) {
        reply_result(message, D3_RESULT(114, 1));
        return;
    }
    static const char interface_name[] = "android.gui.IGraphicBufferProducer";
    const uint16_t *token = (const uint16_t *)(data + 2);
    if (data[1] != sizeof interface_name - 1u) {
        reply_result(message, D3_RESULT(114, 1));
        return;
    }
    for (size_t index = 0; index < sizeof interface_name; index++) {
        if (token[index] != (uint8_t)interface_name[index]) {
            reply_result(message, D3_RESULT(114, 1));
            return;
        }
    }
    const uint32_t *values = (const uint32_t *)((const uint8_t *)data + argument_offset);
    const size_t value_count = (data_size - argument_offset) / 4u;
    uint32_t response[128] = {4, 16, 0, 20};
    int32_t status = -38;
    size_t result_count = 0;
    const size_t required_size = transaction == 1 ? 396u : transaction == 3 ? 72u :
                                 transaction == 10 || transaction == 7 ? 36u :
                                 transaction == 9 ? 24u : 20u;
    if (output_size < required_size) {
        reply_result(message, D3_RESULT(114, 1));
        return;
    }
    pthread_mutex_lock(&g_vi_mutex);
    if (transaction == 9 && value_count >= 1) {
        status = 0;
        result_count = 1;
        switch (values[0]) {
        case 0: case 6: response[4] = g_vi_width; break;
        case 1: case 7: response[4] = g_vi_height; break;
        case 2: response[4] = g_vi_format; break;
        case 3: response[4] = 1; break;
        case 4: response[4] = 1; break;
        case 5: response[4] = 0; break;
        case 8: case 9: case 10: case 11: case 12: response[4] = 0; break;
        default: status = -22; break;
        }
    } else if (transaction == 10 && value_count >= 3) {
        result_count = 4;
        response[4] = g_vi_width;
        response[5] = g_vi_height;
        if (values[0] || !values[1] || values[1] > 4 || g_vi_api)
            status = -22;
        else {
            g_vi_api = values[1];
            status = 0;
        }
    } else if (transaction == 11 && value_count >= 1) {
        if (g_vi_api != values[0])
            status = -22;
        else {
            g_vi_api = 0;
            for (size_t index = 0; index < 64; index++) {
                vi_release_buffer(&g_vi_buffers[index]);
            }
            status = 0;
        }
    } else if (transaction == 2 && value_count >= 1) {
        int busy = 0;
        for (size_t index = 0; index < 64; index++)
            busy |= g_vi_buffers[index].dequeued;
        if (values[0] > 64 || busy)
            status = -22;
        else {
            g_vi_buffer_count = values[0] ? values[0] : 3;
            status = 0;
        }
    } else if (transaction == 14 && value_count >= 2) {
        const uint32_t slot = values[0];
        status = -22;
        if (slot < 64 && !g_vi_buffers[slot].dequeued) {
            if (values[1] == 0) {
                vi_release_buffer(&g_vi_buffers[slot]);
                status = 0;
            } else if (value_count >= 95 && values[2] == 364 && values[3] == 0) {
                const uint32_t *description = values + 4;
                uint64_t address = 0, size = 0;
                if (description[1] && description[1] <= 8192 && description[2] &&
                    description[2] <= 8192 && description[3] >= description[1] &&
                    d3_nv_buffer_pin(description[11], &address, &size) == 0) {
                    int valid = description[30] < size;
#ifdef D3_WITH_GPU
                    if (valid)
                        valid = d3_gpu_import_framebuffer(address, size) == 0;
#endif
                    if (valid) {
                        vi_release_buffer(&g_vi_buffers[slot]);
                        g_vi_buffers[slot] = (ViBuffer){.address = address, .size = size, .populated = 1};
                        memcpy(g_vi_buffers[slot].data, description, 364);
                        g_vi_width = description[1];
                        g_vi_height = description[2];
                        g_vi_format = description[4];
                        if (g_vi_buffer_count <= slot)
                            g_vi_buffer_count = slot + 1;
                        status = 0;
                        slog("vi preallocated slot=%u %ux%u stride=%u nvmap=%u offset=%#x format=%u",
                             slot, description[1], description[2], description[3], description[11],
                             description[30], description[18]);
                    } else {
                        d3_nv_buffer_unpin(description[11]);
                    }
                }
            }
        }
    } else if (transaction == 3 && value_count >= 5) {
        result_count = 13;
        response[4] = UINT32_MAX;
        response[5] = 1;
        response[6] = 36;
        for (size_t index = 0; index < 4; index++)
            response[9 + index * 2] = UINT32_MAX;
        status = g_vi_api ? -11 : -19;
        for (uint32_t index = 0; g_vi_api && index < g_vi_buffer_count; index++) {
            ViBuffer *buffer = &g_vi_buffers[index];
            if (!buffer->populated || buffer->dequeued ||
                (values[1] && values[1] != buffer->data[1]) ||
                (values[2] && values[2] != buffer->data[2]) ||
                (values[3] && values[3] != buffer->data[4]) ||
                (values[4] & buffer->data[5]) != values[4])
                continue;
            buffer->dequeued = 1;
            response[4] = index;
            status = buffer->requested ? 0 : 1;
            break;
        }
    } else if (transaction == 1 && value_count >= 1) {
        status = -22;
        result_count = 1;
        if (values[0] < 64 && g_vi_buffers[values[0]].populated &&
            g_vi_buffers[values[0]].dequeued) {
            ViBuffer *buffer = &g_vi_buffers[values[0]];
            response[4] = 1;
            response[5] = 364;
            memcpy(response + 7, buffer->data, 364);
            result_count = 94;
            buffer->requested = 1;
            status = 0;
        }
    } else if (transaction == 8 && value_count >= 12) {
        status = -22;
        if (values[0] < 64 && g_vi_buffers[values[0]].dequeued &&
            values[1] == 36 && values[2] == 0 && values[3] == 0) {
            g_vi_buffers[values[0]].dequeued = 0;
            status = 0;
        }
    } else if (transaction == 7 && value_count >= 24) {
        result_count = 4;
        response[4] = g_vi_width;
        response[5] = g_vi_height;
        status = -22;
        if (values[0] < 64 && g_vi_buffers[values[0]].populated &&
            g_vi_buffers[values[0]].dequeued && g_vi_buffers[values[0]].requested &&
            values[1] == 84 && values[2] == 0 && values[15] <= 4) {
            status = -38;
#ifdef D3_WITH_GPU
            ViBuffer *buffer = &g_vi_buffers[values[0]];
            status = d3_gpu_present_guest(buffer->address, buffer->size, buffer->data, values + 3);
            if (status == 0)
                buffer->dequeued = 0;
#endif
        }
    }
    vi_update_events();
    pthread_mutex_unlock(&g_vi_mutex);
    response[0] = (uint32_t)(result_count + 1u) * 4u;
    response[3] = 16u + response[0];
    response[4 + result_count] = (uint32_t)status;
    memcpy((void *)(uintptr_t)output, response, response[3]);
    static unsigned binder_logs;
    if (status || binder_logs++ < 32) slog("binder transact=%u arguments=%zu first=%#x status=%d", transaction, value_count,
         value_count ? values[0] : 0, status);
    reply_ok(message, 0);
}

static void vi_app_command(Message *m, uint32_t command, uint32_t session) {
    (void)session;
    switch (command) {
    case 100: /* GetRelayService */
    case 101: /* GetSystemDisplayService */
    case 102: /* GetManagerDisplayService */
    case 103: /* GetIndirectDisplayTransactionService */
    {
        uint32_t handle = d3_handle_alloc(D3_OBJ_SESSION, command == 100 ? "dispdrv" : "vi-sub",
                                         command == 100 ? PORT_BINDER : PORT_VI_APP);
        slog("IApplicationDisplayService cmd=%u -> session %#x", command, handle);
        if (handle == 0)
            reply_result(m, D3_RESULT(21, 7));
        else
            reply_handle(m, handle);
        break;
    }
    case 1000: /* ListDisplays: one display */
        slog("IApplicationDisplayService::ListDisplays -> 1");
        reply_u64(m, 1);
        break;
    case 1010: /* OpenDisplay */
    case 1011: /* OpenDefaultDisplay */
        slog("IApplicationDisplayService cmd=%u -> display id 1", command);
        reply_u64(m, 1);
        break;
    case 1020: /* CloseDisplay */
        reply_ok(m, 1);
        break;
    case 2012:
    case 2030:
    case 2020: {
        uint64_t address = 0;
        size_t size = 0;
        const uint32_t parcel[15] = {
            0x28, 0x10, 4, 0x38, 2, 1, 1, 0, 0, 0, 0x70736964, 0x00767264, 0, 0, 0
        };
        if (!message_io_buffer(m, 1, 0, &address, &size) || size < sizeof parcel) {
            reply_result(m, D3_RESULT(114, 1));
            break;
        }
        memcpy((void *)(uintptr_t)address, parcel, sizeof parcel);
        slog("vi layer cmd=%u -> producer=1 parcel=%zu", command, sizeof parcel);
        reply_prepare(m, 0, command == 2020 ? 4 : 6, m->domain ? 1 : 0);
        const uint64_t values[2] = {command == 2020 ? sizeof parcel : 1, sizeof parcel};
        memcpy(&m->w[m->payload + 4], values, command == 2020 ? 8 : 16);
        reply_send(m);
        break;
    }
    case 1102: /* GetDisplayResolution -> width, height */
        slog("IApplicationDisplayService::GetDisplayResolution -> 1920x1080");
        reply_prepare(m, 0, 6, m->domain ? 1 : 0);
        {
            uint64_t width = 1920, height = 1080;
            memcpy(&m->w[m->payload + 4], &width, sizeof width);
            memcpy(&m->w[m->payload + 6], &height, sizeof height);
        }
        reply_send(m);
        break;
    default:
        slog("IApplicationDisplayService cmd=%u -> ok (stub)", command);
        reply_ok(m, 1);
        break;
    }
}

/* ---------------------------------------------------------------- hid     */

/* nn::hid::InitializeNpad needs the server-side applet resource: an id plus the
   256 KiB shared memory block that carries the Npad state.  The title maps the
   block itself with MapSharedMemory, so a zero-filled allocation is enough for
   the boot to continue and the block's layout stays the title's business. */
#define D3_HID_SHARED_MEMORY_SIZE (256u * 1024u)
#define D3_HID_ARUID 1u

/* The Npad section uses a 0x5000 entry per id, starting at 0x9A00. */
#define D3_HID_NPAD_BASE 0x9A00u
#define D3_HID_NPAD_ENTRY 0x5000u
#define D3_HID_STYLE_TAG 0x0u
#define D3_HID_STYLE_FULLKEY 0x1u
#define D3_HID_STYLE_HANDHELD 0x2u
#define D3_HID_ASSIGNMENT 0x4u    /* NpadJoyAssignmentMode::Dual */
#define D3_HID_FULLKEY_LIFO 0x28u
#define D3_HID_HANDHELD_LIFO 0x378u
#define D3_HID_LIFO_STATES 17u
#define D3_HID_LIFO_ENTRY 0x30u   /* AtomicStorage<NPadGenericState> */
#define D3_HID_CONNECTION 0x28u   /* NPadGenericState::connection_status */

static pthread_mutex_t g_hid_mutex = PTHREAD_MUTEX_INITIALIZER;
static uint64_t g_hid_base;
static uint64_t g_hid_mapping;
static uint64_t g_hid_sample = 1;

static int32_t hid_axis(int32_t value) {
    return value < -32767 ? -32767 : value > 32767 ? 32767 : value;
}

/* Publish a fresh sample even while a button is held. The SDK reads the atomic
   sampling number before and after copying the slot, then reads the tail. */
void d3_hid_update(uint64_t buttons, int32_t lx, int32_t ly, int32_t rx, int32_t ry) {
    pthread_mutex_lock(&g_hid_mutex);
    static uint64_t last_buttons;
    if (last_buttons != buttons) {
        __android_log_print(ANDROID_LOG_INFO, "d3input", "buttons=%#llx sample=%llu mapping=%#llx",
            (unsigned long long)buttons, (unsigned long long)g_hid_sample, (unsigned long long)g_hid_mapping);
        last_buttons = buttons;
    }
    if (g_hid_base) {
        uint8_t *lifo = (uint8_t *)(uintptr_t)(g_hid_base + D3_HID_NPAD_BASE + D3_HID_FULLKEY_LIFO);
        uint64_t *header = (uint64_t *)lifo;
        const uint64_t tail = (header[2] + 1) % D3_HID_LIFO_STATES;
        uint8_t *entry = lifo + 0x20 + tail * D3_HID_LIFO_ENTRY;
        const uint64_t sample = ++g_hid_sample;
        int32_t axes[4] = {hid_axis(lx), hid_axis(ly), hid_axis(rx), hid_axis(ry)};
        if (axes[0] < -16383) buttons |= 1ULL << 16;
        if (axes[1] >  16383) buttons |= 1ULL << 17;
        if (axes[0] >  16383) buttons |= 1ULL << 18;
        if (axes[1] < -16383) buttons |= 1ULL << 19;
        if (axes[2] < -16383) buttons |= 1ULL << 20;
        if (axes[3] >  16383) buttons |= 1ULL << 21;
        if (axes[2] >  16383) buttons |= 1ULL << 22;
        if (axes[3] < -16383) buttons |= 1ULL << 23;
        __atomic_store_n((uint64_t *)entry, 0, __ATOMIC_RELEASE);
        memcpy(entry + 8, &sample, 8);
        memcpy(entry + 16, &buttons, 8);
        memcpy(entry + 24, axes, sizeof axes);
        const uint32_t connected = 3;
        memcpy(entry + D3_HID_CONNECTION, &connected, sizeof connected);
        __atomic_store_n((uint64_t *)entry, sample, __ATOMIC_RELEASE);
        header[0] = sample;
        header[3] = header[3] < D3_HID_LIFO_STATES ? header[3] + 1 : D3_HID_LIFO_STATES;
        __atomic_store_n(header + 2, tail, __ATOMIC_RELEASE);
    }
    pthread_mutex_unlock(&g_hid_mutex);
}

void d3_hid_unmap(uint64_t address) {
    pthread_mutex_lock(&g_hid_mutex);
    if (g_hid_mapping == address) {
        if (g_hid_base != g_hid_mapping)
            munmap((void *)(uintptr_t)g_hid_base, D3_HID_SHARED_MEMORY_SIZE);
        g_hid_base = g_hid_mapping = 0;
    }
    pthread_mutex_unlock(&g_hid_mutex);
}

static void hid_seed_lifo(uint8_t *lifo) {
    /* Lifo header: timestamp, total buffer count, tail index, live count.  One
       entry is enough: it says the pad exists and no button is down. */
    int64_t header[4] = {0, (int64_t)D3_HID_LIFO_STATES, 0, 1};
    memcpy(lifo, header, sizeof header);
    int64_t *entry = (int64_t *)(lifo + 0x20);
    memset(entry, 0, D3_HID_LIFO_ENTRY);
    entry[0] = 1; /* sampling number of the atomic slot */
    entry[1] = 1; /* sampling number of the state */
    uint32_t connected = 0x3u; /* is_connected | is_wired */
    memcpy((uint8_t *)entry + D3_HID_CONNECTION, &connected, sizeof connected);
}

/* The title maps the hid block itself; this fills in the one pad it must see. */
void d3_hid_seed(uint64_t base) {
    d3_hid_map(base, base);
}

void d3_hid_map(uint64_t base, uint64_t writable_alias) {
    pthread_mutex_lock(&g_hid_mutex);
    if (g_hid_base && g_hid_base != g_hid_mapping)
        munmap((void *)(uintptr_t)g_hid_base, D3_HID_SHARED_MEMORY_SIZE);
    uint8_t *block = (uint8_t *)(uintptr_t)(writable_alias + D3_HID_NPAD_BASE);
    uint32_t style = D3_HID_STYLE_FULLKEY;
    uint32_t assignment = 0; /* NpadJoyAssignmentMode::Dual */
    uint32_t color_ok = 0;   /* ColorAttribute::Ok */
    memcpy(block + D3_HID_STYLE_TAG, &style, sizeof style);
    memcpy(block + D3_HID_ASSIGNMENT, &assignment, sizeof assignment);
    memcpy(block + 0x8, &color_ok, sizeof color_ok);
    hid_seed_lifo(block + D3_HID_FULLKEY_LIFO);
    g_hid_base = writable_alias;
    g_hid_mapping = base;
    g_hid_sample = 1;
    pthread_mutex_unlock(&g_hid_mutex);
    slog("hid: seeded npad 0 (FullKey) at %#" PRIx64, base + D3_HID_NPAD_BASE);
}

static void hid_applet_resource_command(Message *m, uint32_t command) {
    if (command != 0) {
        unsupported_command(m, D3_IF_HID_APPLET_RESOURCE, command);
        return;
    }
    const uint32_t handle =
        d3_handle_alloc(D3_OBJ_SHARED_MEM, "hid-shmem", D3_HID_SHARED_MEMORY_SIZE);
    if (handle == 0) {
        if (m->domain)
            reply_domain(m, D3_RESULT(21, 7), 1);
        else
            reply_result(m, D3_RESULT(21, 7));
        return;
    }
    slog("hid::IAppletResource::GetSharedMemoryHandle -> %#x", handle);
    reply_prepare_handle(m, 1, 0, m->domain, REPLY_COPY_HANDLE);
    m->w[m->handle_slot_out] = handle;
    reply_send(m);
}

static void hid_command(Message *m, uint32_t command, uint32_t session) {
    /* The styles the title registered with SetSupportedNpadStyleSet. */
    static uint32_t g_hid_style;
    switch (command) {
    case 0: {
        g_trace_request = 1;
        const uint64_t aruid = (uint64_t)m->w[m->magic + 4] | ((uint64_t)m->w[m->magic + 5] << 32);
        if (m->domain) {
            const uint32_t object = domain_add(session, D3_IF_HID_APPLET_RESOURCE);
            slog("hid::CreateAppletResource aruid=%#" PRIx64 " -> object %u", aruid, object);
            if (object == 0)
                reply_domain(m, D3_RESULT(21, 7), 1);
            else
                reply_domain_object(m, object);
        } else {
            const uint32_t handle =
                d3_handle_alloc(D3_OBJ_SESSION, "hid-applet", PORT_HID_APPLET_RESOURCE);
            slog("hid::CreateAppletResource aruid=%#" PRIx64 " -> session %#x", aruid, handle);
            if (handle == 0) {
                reply_result(m, D3_RESULT(21, 7));
            } else {
                reply_prepare_handle(m, 1, 0, 0, REPLY_MOVE_HANDLE);
                m->w[m->handle_slot_out] = handle;
                reply_send(m);
            }
        }
        break;
    }
    case 100: /* SetSupportedNpadStyleSet(u64 aruid, u32 style_set) */
        g_hid_style = m->w[m->magic + 4];
        slog("hid::SetSupportedNpadStyleSet -> %#x", g_hid_style);
        reply_ok(m, 1);
        break;
    case 101: /* GetSupportedNpadStyleSet(Out<u32>, u64 aruid) */
        /* The console supports the styles the title registered; with nothing
           registered yet, a handheld tablet still offers FullKey and Handheld. */
        slog("hid::GetSupportedNpadStyleSet -> %#x", g_hid_style ? g_hid_style : 0x3u);
        reply_prepare(m, 0, 2, m->domain ? 1 : 0);
        m->w[m->payload + 4] = g_hid_style ? g_hid_style : 0x3u;
        reply_send(m);
        break;
    case 102: /* SetSupportedNpadIdType(aruid, NpadIdType[]) */
    case 103: /* ActivateNpad(aruid) */
    case 104: /* DeactivateNpad(aruid) */
    case 120: /* SetNpadJoyHoldType(aruid, hold_type) */
    case 122: /* SetNpadHandheldActivationMode(aruid, mode) */
        slog("hid cmd=%u -> ok", command);
        reply_ok(m, 1);
        break;
    case 106: { /* AcquireNpadStyleSetUpdateEventHandle(Out<CopyHandle>, aruid, u32, u64) */
        extern void d3_event_set(uint32_t handle, int signaled);
        const uint32_t event = d3_handle_alloc(D3_OBJ_EVENT, "hid-style-set", 0);
        /* Level triggered: the style set the title will read never changes. */
        d3_event_set(event, 1);
        d3_handle_set_arg(event, 1);
        slog("hid::AcquireNpadStyleSetUpdateEventHandle -> %#x", event);
        if (m->domain)
            reply_domain_handle(m, event);
        else
            reply_handle(m, event);
        break;
    }
    case 203: { /* CreateActiveVibrationDeviceList must return a real interface. */
        if (m->domain) {
            uint32_t object = domain_add(session, D3_IF_HID_VIBRATION);
            if (object) reply_domain_object(m, object);
            else reply_service_result(m, D3_RESULT(21, 7));
        } else {
            uint32_t handle = d3_handle_alloc(D3_OBJ_SESSION, "hid-vibration", PORT_HID_VIBRATION);
            if (handle) reply_handle(m, handle);
            else reply_service_result(m, D3_RESULT(21, 7));
        }
        break;
    }
    case 200: /* No emulated vibration motor. */
    case 202:
    case 205:
    case 208:
    case 211:
        reply_prepare(m, 0, command == 202 ? 4 : 2, m->domain);
        reply_send(m);
        break;
    default:
        /* nn::hid treats a failed call as fatal, and the boot only needs the
           server to exist: acknowledge, leaving the out parameters zeroed. */
        if (g_loud < 4096) {
            g_loud++;
            slog("hid cmd=%#x -> ok (stub)", command);
        }
        reply_ok(m, 6);
        break;
    }
}

static void vi_manager_command(Message *m, uint32_t command, uint32_t session) {
    if (command == 2 || command == 1 || command == 0) { /* GetDisplayService */
        if (m->domain) {
            uint32_t object = domain_add(session, D3_IF_VI_APP);
            slog("IDisplayManager cmd=%u -> display object %u", command, object);
            if (object == 0)
                reply_domain(m, D3_RESULT(21, 7), 1);
            else
                reply_domain_object(m, object);
        } else {
            uint32_t handle = d3_handle_alloc(D3_OBJ_SESSION, "vi-app", PORT_VI_APP);
            slog("IDisplayManager cmd=%u -> display session %#x", command, handle);
            if (handle == 0)
                reply_result(m, D3_RESULT(21, 7));
            else
                reply_handle(m, handle);
        }
        return;
    }
    slog("IDisplayManager cmd=%u -> stub", command);
    reply_ok(m, 1);
}

/* ----------------------------------------------- library applet framework */

/* The title reaches the applet framework whenever its own start-up sequence
   wants a system applet (the Controller applet here).  Every step of that path
   is a call the SDK aborts on if it fails (sdk+0x356d80: "abort unless zero"),
   so the framework has to answer with real objects instead of unsupported:
   IApplicationProxy handles out the creator, the creator hands out an applet
   accessor, and the launch parameter travels in and out as a storage.  Nothing
   runs an applet process here: the accessor reports one that starts and finishes
   at once, which is what an emulated (HLE) applet looks like to the title. */

/* Interfaces the framework hands out.  No title-facing port carries them, so
   they stay out of the generated names header. */
#define D3_IF_STORAGE_ACCESSOR 0x10007
#define D3_IF_TRANSFER_STORAGE_ACCESSOR 0x10008

#define STORAGE_SLOTS 32
#define STORAGE_MAX_BYTES (256u * 1024u)

typedef struct {
    int used;
    uint32_t size;
    uint8_t *data;
} HostStorage;

static HostStorage g_storages[STORAGE_SLOTS];
static uint32_t g_storage_next;

/* Storage ids are the slot index plus one, the same convention as domain ids.
   A full table recycles the oldest slot because the applet path only needs a
   handful of live storages at a time. */
static uint32_t storage_create(uint64_t size) {
    if (size > STORAGE_MAX_BYTES)
        size = STORAGE_MAX_BYTES;
    for (uint32_t probe = 0; probe < STORAGE_SLOTS; probe++) {
        const uint32_t index = (g_storage_next + probe) % STORAGE_SLOTS;
        HostStorage *storage = &g_storages[index];
        if (storage->used && probe + 1 < STORAGE_SLOTS)
            continue;
        free(storage->data);
        storage->data = (uint8_t *)calloc(1, (size_t)(size ? size : 1));
        if (!storage->data) {
            storage->used = 0;
            storage->size = 0;
            return 0;
        }
        storage->used = 1;
        storage->size = (uint32_t)size;
        g_storage_next = (index + 1) % STORAGE_SLOTS;
        return index + 1;
    }
    return 0;
}

static HostStorage *storage_of(uint64_t id) {
    if (id == 0 || id > STORAGE_SLOTS)
        return NULL;
    HostStorage *storage = &g_storages[id - 1];
    return storage->used ? storage : NULL;
}

/* The first buffer descriptor of a request: X descriptors come first (two
   words), then A/B/W (three words).  A storage accessor copies through it. */
static int message_io_buffer(const Message *message, int output, size_t wanted,
                             uint64_t *address, size_t *size) {
    const uint32_t counts = message->w[0] >> 16;
    const size_t statics = counts & 15u;
    const size_t sends = (counts >> 4u) & 15u;
    const size_t receives = (counts >> 8u) & 15u;
    const size_t exchanges = (counts >> 12u) & 15u;
    const size_t mapped = message->descriptor_slot + statics * 2u;
    const size_t mapped_end = mapped + (sends + receives + exchanges) * 3u;
    const size_t raw = message->w[1] & 0x3ffu;
    const uint32_t mode = (message->w[1] >> 10u) & 15u;
    const size_t pointers = mode < 2 ? 0 : mode == 2 ? 1 : mode - 2;
    *address = 0;
    *size = 0;
    if (mapped_end > MESSAGE_WORDS || raw > MESSAGE_WORDS - mapped_end ||
        pointers > (MESSAGE_WORDS - mapped_end - raw) / 2u)
        return 0;
    for (size_t category = 0; category < 3; category++) {
        const size_t count = category == 0 ? (output ? 0 : statics) :
                             category == 1 ? (output ? receives + exchanges : sends) :
                             (output ? pointers : 0);
        for (size_t index = 0; index < count; index++) {
            uint64_t candidate;
            uint64_t bytes;
            if (category == 0) {
                const size_t slot = message->descriptor_slot + index * 2u;
                const uint32_t flags = message->w[slot];
                candidate = message->w[slot + 1] | ((uint64_t)((flags >> 12u) & 15u) << 32u) |
                            ((uint64_t)((flags >> 6u) & 7u) << 36u);
                bytes = flags >> 16u;
            } else if (category == 1) {
                const size_t slot = mapped + ((output ? sends : 0) + index) * 3u;
                const uint32_t flags = message->w[slot + 2];
                candidate = message->w[slot + 1] | ((uint64_t)((flags >> 28u) & 15u) << 32u) |
                            ((uint64_t)((flags >> 2u) & 7u) << 36u);
                bytes = message->w[slot] | ((uint64_t)((flags >> 24u) & 15u) << 32u);
            } else {
                const size_t slot = mapped_end + raw + index * 2u;
                candidate = message->w[slot] | ((uint64_t)(message->w[slot + 1] & 0xffffu) << 32u);
                bytes = message->w[slot + 1] >> 16u;
            }
            if (!candidate || !bytes)
                continue;
            if (wanted-- == 0) {
                *address = candidate;
                *size = (size_t)bytes;
                return 1;
            }
        }
    }
    return 0;
}

static int message_buffer(const Message *m, uint64_t *address, size_t *size) {
    const size_t slot = m->descriptor_slot;
    const uint32_t counts = m->w[0] >> 16;
    const size_t statics = counts & 0xfu;
    const size_t sends = (counts >> 4) & 0xfu;
    const size_t receives = (counts >> 8) & 0xfu;
    const size_t exchanges = (counts >> 12) & 0xfu;
    *address = 0;
    *size = 0;
    for (size_t index = 0; index < statics; index++) {
        const size_t descriptor = slot + 2u * index;
        if (descriptor + 1u >= MESSAGE_WORDS)
            return 0;
        const uint32_t low = m->w[descriptor];
        const uint32_t high = m->w[descriptor + 1];
        *size = (low >> 16) & 0xffffu;
        *address = (uint64_t)high | ((uint64_t)((low >> 12) & 0xfu) << 32) |
                   ((uint64_t)((low >> 6) & 0x7u) << 36);
        if (*address && *size)
            return 1;
    }
    const size_t mapped_slot = slot + 2u * statics;
    const size_t mapped_count = sends + receives + exchanges;
    for (size_t index = 0; index < mapped_count; index++) {
        const size_t descriptor = mapped_slot + 3u * index;
        if (descriptor + 2u >= MESSAGE_WORDS)
            return 0;
        const uint32_t size_low = m->w[descriptor];
        const uint32_t addr_low = m->w[descriptor + 1];
        const uint32_t flags = m->w[descriptor + 2];
        *size = (uint64_t)size_low | ((uint64_t)((flags >> 24) & 0xfu) << 32);
        *address = (uint64_t)addr_low | ((uint64_t)((flags >> 28) & 0xfu) << 32) |
                   ((uint64_t)((flags >> 2) & 0x7u) << 36);
        if (*address && *size)
            return 1;
    }
    const uint32_t receive_mode = (m->w[1] >> 10) & 0xfu;
    const size_t receive_count = receive_mode < 2 ? 0 : receive_mode == 2 ? 1 : receive_mode - 2;
    const size_t receive_slot = mapped_slot + 3u * mapped_count + (m->w[1] & 0x3ffu);
    if (receive_slot > MESSAGE_WORDS || receive_count > (MESSAGE_WORDS - receive_slot) / 2u)
        return 0;
    for (size_t index = 0; index < receive_count; index++) {
        const size_t descriptor = receive_slot + 2u * index;
        const uint32_t low = m->w[descriptor];
        const uint32_t high = m->w[descriptor + 1];
        *address = (uint64_t)low | ((uint64_t)(high & 0xffffu) << 32);
        *size = high >> 16;
        if (*address && *size)
            return 1;
    }
    *address = 0;
    *size = 0;
    return 0;
}

/* The domain object id a reply hands the guest for a fresh storage. */
static uint32_t storage_object(uint32_t session, int iface, uint64_t size) {
    const uint32_t id = storage_create(size);
    if (id == 0)
        return 0;
    const uint32_t object = domain_add(session, iface);
    if (object == 0) {
        free(storage_of(id)->data);
        g_storages[id - 1].used = 0;
        return 0;
    }
    g_domain[object - 1].arg = id;
    return object;
}

static void application_pop_launch_parameter(Message *message, uint32_t session) {
    static int consumed;
    if (!message_arguments(message, 4)) {
        reply_service_result(message, D3_RESULT(128, 1));
        return;
    }
    const uint32_t kind = message->w[message->magic + 4];
    if (kind != 2 || consumed) {
        reply_service_result(message, D3_RESULT(128, 2));
        return;
    }
    const uint32_t object = storage_object(session, D3_IF_STORAGE, 0x88);
    if (!object) {
        reply_service_result(message, D3_RESULT(21, 7));
        return;
    }
    HostStorage *storage = storage_of(g_domain[object - 1].arg);
    const uint32_t header[2] = {0xc79497ca, 1};
    memcpy(storage->data, header, sizeof header);
    memcpy(storage->data + 8, g_local_user, sizeof g_local_user);
    consumed = 1;
    slog("IApplicationFunctions::PopLaunchParameter -> local preselected user object %u", object);
    reply_domain_object(message, object);
}

/* ILibraryAppletCreator (the object IApplicationProxy::GetLibraryAppletCreator
   hands out, iface 18). */
#include "d3_keyboard_service.inc"

static void library_applet_creator_command(Message *m, uint32_t command, uint32_t session) {
    switch (command) {
    case 0:   /* CreateLibraryApplet(AppletId, LibraryAppletMode) */
    case 3: { /* CreateLibraryAppletEx */
        const uint32_t applet = m->w[m->magic + 4];
        const uint32_t mode = m->w[m->magic + 5];
        const uint32_t object = domain_add(session, D3_IF_LIBRARY_APPLET_ACCESSOR);
        slog("ILibraryAppletCreator::CreateLibraryApplet applet=%#x mode=%#x -> object %u", applet,
             mode, object);
        if (object == 0) {
            reply_domain(m, D3_RESULT(21, 7), 1);
            break;
        }
        g_domain[object - 1].arg = applet;
        reply_domain_object(m, object);
        break;
    }
    case 1: /* TerminateAllLibraryApplets */
        reply_domain(m, 0, 1);
        break;
    case 2: /* AreAnyLibraryAppletsLeft(Out<bool>) */
        reply_prepare(m, 0, 2, 1);
        m->w[m->payload + 4] = 0;
        reply_send(m);
        break;
    case 11: { /* CreateTransferMemoryStorage(bool writable, s64 size, CopyHandle) */
        uint64_t size = 0;
        if (message_arguments(m, 16)) memcpy(&size, &m->w[m->magic + 6], 8);
        const uint32_t handle = m->copy_handles ? m->w[m->handle_slot] : 0;
        const uint64_t address = d3_handle_kind(handle) == D3_OBJ_TRANSFER_MEM ? d3_handle_arg(handle) : 0;
        uint32_t object = size && size <= STORAGE_MAX_BYTES && address ? storage_object(session, D3_IF_STORAGE, size) : 0;
        if (object && !guest_read(storage_of(g_domain[object - 1].arg)->data, address, (size_t)size)) {
            domain_close(session, object); object = 0;
        }
        if (object) reply_domain_object(m, object);
        else reply_service_result(m, D3_RESULT(21, 7));
        break;
    }
    case 10: { /* CreateStorage(u64 size, Out<SharedPointer<IStorage>>) */
        const uint64_t size = (uint64_t)m->w[m->magic + 4] |
                              ((uint64_t)m->w[m->magic + 5] << 32);
        const uint32_t object = storage_object(session, D3_IF_STORAGE, size);
        slog("ILibraryAppletCreator::CreateStorage size=%llu -> object %u",
             (unsigned long long)size, object);
        if (object == 0)
            reply_domain(m, D3_RESULT(21, 7), 1);
        else
            reply_domain_object(m, object);
        break;
    }
    default:
        unsupported_command(m, D3_IF_LIBRARY_APPLET_CREATOR, command);
        break;
    }
}

/* A library applet accessor that is always already finished.  The title pushes
   its launch parameter in, waits for the applet to run, then pops the result
   out; answering every step keeps that sequence moving without an applet. */
static void library_applet_accessor_command(Message *m, uint32_t command, uint32_t session) {
    DomainObject *object = NULL;
    if (m->domain_object >= 1 && m->domain_object <= DOMAIN_SLOTS)
        object = &g_domain[m->domain_object - 1];
    switch (command) {
    case 0: { /* GetAppletStateChangedEvent(Out<CopyHandle>) */
        extern void d3_event_set(uint32_t handle, int signaled);
        const uint32_t event = d3_handle_alloc(D3_OBJ_EVENT, "applet-state", 0);
        if (object && object->arg == 0x11) d3_handle_set_arg(event, 1);
        if (object)
            object->event = event;
        d3_event_set(event, object && object->arg == 0x11 ? object->initialized : 1);
        slog("ILibraryAppletAccessor::GetAppletStateChangedEvent -> %#x", event);
        reply_domain_handle(m, event);
        break;
    }
    case 1: /* IsCompleted(Out<bool>) */
        reply_prepare(m, 0, 2, 1);
        m->w[m->payload + 4] = object && object->arg == 0x11 ? object->initialized : 1;
        reply_send(m);
        break;
    case 10: { /* Start */
        extern void d3_event_set(uint32_t handle, int signaled);
        slog("ILibraryAppletAccessor::Start applet=%#x", object ? (uint32_t)object->arg : 0u);
        if (object) {
            if (object->arg == 0x11 && keyboard_start(object) != 0) {
                reply_service_result(m, D3_RESULT(128, 1));
                break;
            }
            if (object->arg != 0x11) object->initialized = 1;
            d3_event_set(object->event, object->initialized);
        }
        /* The applet is finished the moment it starts, so the next one may be
           launched right away. */
        d3_event_set(g_applet_launchable, 1);
        reply_domain(m, 0, 1);
        break;
    }
    case 20: /* RequestExit */
    case 25: /* Terminate */
        reply_domain(m, 0, 1);
        break;
    case 30: /* GetResult(Out<u32>) */
        reply_prepare(m, 0, 2, 1);
        m->w[m->payload + 4] = 0;
        reply_send(m);
        break;
    case 50: /* SetOutOfFocusApplicationSuspendingEnabled(bool) */
        if (object)
            object->out_of_focus_suspending = (int)m->w[m->magic + 4];
        reply_domain(m, 0, 1);
        break;
    case 60: /* PresetLibraryAppletGpuTimeSliceZero */
        reply_domain(m, 0, 1);
        break;
    case 100: /* PushInData(SharedPointer<IStorage>) */
    case 103: /* PushInteractiveInData */
        if (object && object->arg == 0x11 && command == 103) {
            uint32_t input = m->w[m->magic + 4];
            HostStorage *check = input && input <= DOMAIN_SLOTS && domain_iface(session, input) == D3_IF_STORAGE
                ? storage_of(g_domain[input - 1].arg) : NULL;
            if (!check || check->size < 4) { reply_service_result(m, D3_RESULT(128, 1)); break; }
            uint32_t result = keyboard_u32(check->data, 0);
            object->interactive_storage = 0;
            if (result == 0) {
                object->initialized = 1;
                extern void d3_event_set(uint32_t, int);
                d3_event_set(object->event, 1);
            } else if (keyboard_start(object) != 0) {
                reply_service_result(m, D3_RESULT(128, 1)); break;
            }
            slog("keyboard text check result=%u completed=%d", result, object->initialized);
        }
        if (object && object->arg == 0x11 && command == 100 && object->input_count < 4) {
            uint32_t input = m->w[m->magic + 4];
            if (input && input <= DOMAIN_SLOTS && domain_iface(session, input) == D3_IF_STORAGE)
                object->inputs[object->input_count++] = (uint32_t)g_domain[input - 1].arg;
        }
        slog("ILibraryAppletAccessor cmd %u (in data) args=%#x %#x %#x %#x", command,
             m->w[m->magic + 4], m->w[m->magic + 5], m->w[m->magic + 6], m->w[m->magic + 7]);
        reply_domain(m, 0, 1);
        break;
    case 101: /* PopOutData(Out<SharedPointer<IStorage>>) */
    case 104: { /* PopInteractiveOutData */
        if (object && object->arg == 0x10) {
            const uint32_t out = storage_object(session, D3_IF_STORAGE, 0x18);
            if (!out) { reply_service_result(m, D3_RESULT(21, 7)); break; }
            HostStorage *storage = storage_of(g_domain[out - 1].arg);
            memcpy(storage->data + 8, g_local_user, sizeof g_local_user);
            reply_domain_object(m, out);
            break;
        }
        if (object && (object->arg == 0x13 || object->arg == 0x14 || object->arg == 0x17)) {
            const uint32_t out = storage_object(session, D3_IF_STORAGE, 0x1010);
            if (!out) { reply_service_result(m, D3_RESULT(21, 7)); break; }
            HostStorage *storage = storage_of(g_domain[out - 1].arg);
            const uint32_t exit_requested = 2;
            memcpy(storage->data, &exit_requested, 4);
            slog("offline web applet unavailable: returning ExitRequested");
            reply_domain_object(m, out);
            break;
        }
        if (object && object->arg == 0x11) {
            uint32_t id = command == 104 ? object->interactive_storage : object->output_storage;
            uint32_t out = id ? domain_add(session, D3_IF_STORAGE) : 0;
            if (out) {
                g_domain[out - 1].arg = id;
                reply_domain_object(m, out);
            } else reply_service_result(m, D3_RESULT(128, 2));
            break;
        }
        /* The Controller applet hands the title a ControllerSupportResultInfo
           (0xC bytes): the player count, the npad id the user chose and whether
           the configuration was accepted.  Reporting "one player, player 1,
           success" is what dismissing the Change Grip/Order screen does on
           hardware, and the title needs it before it will leave the applet. */
        const uint32_t out = storage_object(session, D3_IF_STORAGE, 0xC);
        if (out != 0) {
            HostStorage *storage = storage_of(g_domain[out - 1].arg);
            if (storage && storage->size >= 0xC) {
                storage->data[0] = 1; /* player_count */
                storage->data[1] = 0;
                storage->data[2] = 0;
                storage->data[3] = 0;
                storage->data[4] = 0; /* selected_id: player 1 */
                storage->data[5] = 0;
                storage->data[6] = 0;
                storage->data[7] = 0;
                storage->data[8] = 0; /* ControllerSupportResult::Success */
                storage->data[9] = 0;
                storage->data[10] = 0;
                storage->data[11] = 0;
            }
        }
        slog("ILibraryAppletAccessor cmd %u (out data) -> storage object %u", command, out);
        if (out == 0)
            reply_domain(m, D3_RESULT(21, 7), 1);
        else
            reply_domain_object(m, out);
        break;
    }
    case 105: /* GetPopOutDataEvent(Out<CopyHandle>) */
    case 106: { /* GetPopInteractiveOutDataEvent */
        extern void d3_event_set(uint32_t handle, int signaled);
        const uint32_t event = d3_handle_alloc(D3_OBJ_EVENT, "applet-out-data", 0);
        if (object && object->arg == 0x11) d3_handle_set_arg(event, 1);
        d3_event_set(event, object && object->arg == 0x11
            ? (command == 106 ? object->interactive_storage != 0 : object->initialized) : 1);
        slog("ILibraryAppletAccessor cmd %u (out data event) -> %#x completed=%d interactive=%u", command, event,
            object ? object->initialized : -1, object ? object->interactive_storage : 0);
        reply_domain_handle(m, event);
        break;
    }
    case 120: { /* GetLibraryAppletInfo(Out<LibraryAppletInfo>) */
        reply_prepare(m, 0, 2, 1);
        m->w[m->payload + 4] = object ? (uint32_t)object->arg : 0u;
        m->w[m->payload + 5] = 0;
        reply_send(m);
        break;
    }
    case 160: /* GetIndirectLayerConsumerHandle(Out<u64>) */
        reply_prepare(m, 0, 2, 1);
        m->w[m->payload + 4] = 0;
        m->w[m->payload + 5] = 0;
        reply_send(m);
        break;
    default:
        unsupported_command(m, D3_IF_LIBRARY_APPLET_ACCESSOR, command);
        break;
    }
}

/* IStorage (iface 21): the buffer lives in the host, the accessor copies
   through it. */
static void storage_command(Message *m, uint32_t command, uint32_t session) {
    uint64_t id = 0;
    if (m->domain_object >= 1 && m->domain_object <= DOMAIN_SLOTS)
        id = g_domain[m->domain_object - 1].arg;
    switch (command) {
    case 0:   /* Open(Out<SharedPointer<IStorageAccessor>>) */
    case 1: { /* OpenTransferStorage */
        const int iface = command == 0 ? D3_IF_STORAGE_ACCESSOR : D3_IF_TRANSFER_STORAGE_ACCESSOR;
        const uint32_t object = domain_add(session, iface);
        slog("IStorage::%s storage %llu -> object %u", command == 0 ? "Open" : "OpenTransferStorage",
             (unsigned long long)id, object);
        if (object == 0) {
            reply_domain(m, D3_RESULT(21, 7), 1);
            break;
        }
        g_domain[object - 1].arg = id;
        reply_domain_object(m, object);
        break;
    }
    default:
        unsupported_command(m, D3_IF_STORAGE, command);
        break;
    }
}

/* process_vm_* keeps a mistaken guest pointer from faulting the host thread,
   which matters because these copies run in place of the title's own memcpy. */
static int guest_read(void *dst, uint64_t address, size_t size) {
    struct iovec local = {dst, size};
    struct iovec remote = {(void *)(uintptr_t)address, size};
    return process_vm_readv(getpid(), &local, 1, &remote, 1, 0) == (ssize_t)size;
}

static int guest_write(uint64_t address, const void *src, size_t size) {
    struct iovec local = {(void *)src, size};
    struct iovec remote = {(void *)(uintptr_t)address, size};
#ifdef D3_WITH_GPU
    d3_gpu_begin_cpu_write(address, size);
#endif
    const ssize_t wrote = process_vm_writev(getpid(), &local, 1, &remote, 1, 0);
#ifdef D3_WITH_GPU
    d3_gpu_end_cpu_write();
#endif
    return wrote == (ssize_t)size;
}

static void storage_accessor_command(Message *m, uint32_t command) {
    uint64_t id = 0;
    if (m->domain_object >= 1 && m->domain_object <= DOMAIN_SLOTS)
        id = g_domain[m->domain_object - 1].arg;
    HostStorage *storage = storage_of(id);
    if (!storage) {
        unsupported_command(m, D3_IF_STORAGE_ACCESSOR, command);
        return;
    }
    switch (command) {
    case 0: /* GetSize(Out<s64>) */
        reply_prepare(m, 0, 2, 1);
        memcpy(&m->w[m->payload + 4], &storage->size, sizeof storage->size);
        reply_send(m);
        break;
    case 10:   /* Write(InBuffer, s64 offset) */
    case 11: { /* Read(OutBuffer, s64 offset) */
        uint64_t address = 0;
        size_t size = 0;
        int64_t offset = (int64_t)(((uint64_t)m->w[m->magic + 5] << 32) | m->w[m->magic + 4]);
        const int have_buffer = message_buffer(m, &address, &size);
        slog("IStorageAccessor cmd %u words=%#x %#x %#x %#x buffer=%d address=%#" PRIx64
             " size=%zu offset=%lld storage=%llu",
             command, m->w[m->magic + 4], m->w[m->magic + 5], m->w[m->magic + 6],
             m->w[m->magic + 7], have_buffer, address, size, (long long)offset,
             (unsigned long long)id);
        if (!have_buffer) {
            /* A storage of ours is host memory with no data behind it; a null
               buffer means there is nothing to move, not that the call failed.
               The title treats a failure here as fatal. */
            slog("IStorageAccessor cmd %u without a buffer -> ok: type=%#x counts=%#x "
                 "w0..w24=%#x %#x %#x %#x %#x %#x %#x %#x %#x %#x %#x %#x %#x %#x %#x %#x "
                 "%#x %#x %#x %#x %#x %#x %#x %#x %#x",
                 command, m->w[0] & 0xffffu, m->w[0] >> 16, m->w[0], m->w[1], m->w[2], m->w[3],
                 m->w[4], m->w[5], m->w[6], m->w[7], m->w[8], m->w[9], m->w[10], m->w[11],
                 m->w[12], m->w[13], m->w[14], m->w[15], m->w[16], m->w[17], m->w[18],
                 m->w[19], m->w[20], m->w[21]);
            reply_prepare(m, 0, 2, 1);
            reply_send(m);
            break;
        }
        /* The offset argument is the one raw parameter; clamp rather than fail
           so a mis read argument cannot stop the title's applet sequence. */
        if (offset < 0 || (uint64_t)offset > storage->size)
            offset = 0;
        const size_t room = storage->size - (size_t)offset;
        if (size > room)
            size = room;
        int moved;
        if (command == 10)
            moved = guest_read(storage->data + offset, address, size);
        else
            moved = guest_write(address, storage->data + offset, size);
        slog("IStorageAccessor %s %zu bytes at %#llx -> %d", command == 10 ? "write" : "read",
             size, (unsigned long long)address, moved);
        reply_prepare(m, 0, 2, 1);
        reply_send(m);
        break;
    }
    default:
        unsupported_command(m, D3_IF_STORAGE_ACCESSOR, command);
        break;
    }
}

#include "d3_audio_service.inc"
#include "d3_friend_service.inc"

static void hid_vibration_command(Message *m, uint32_t command) {
    if (command == 0) reply_service_result(m, 0); /* Register a virtual device with no motor. */
    else unsupported_command(m, D3_IF_HID_VIBRATION, command);
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
    case D3_IF_HID_VIBRATION:
        hid_vibration_command(m, m->command);
        break;
    case D3_IF_FRIEND_CREATOR:
    case D3_IF_FRIEND:
    case D3_IF_FRIEND_NOTIFICATION:
        friend_command(m, m->command, handle, iface);
        break;
    case D3_IF_AUDIN:
        audin_command(m, m->command);
        break;
    case D3_IF_AUDOUT:
        audout_command(m, m->command, handle);
        break;
    case D3_IF_AUDIO_OUT:
        audio_out_command(m, m->command, handle);
        break;
    case D3_IF_ACCOUNT_MANAGER:
        if (m->command == 0)
            reply_domain(m, D3_RESULT(124, 200), 1);
        else
            unsupported_command(m, iface, m->command);
        break;
    case D3_IF_TIME:
        time_service_command(m, m->command, handle);
        break;
    case D3_IF_TIME_ZONE:
        unsupported_command(m, iface, m->command);
        break;
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
    case D3_IF_FSP_SRV:
        fsp_srv_command(m, m->command, handle);
        break;
    case D3_IF_SAVE_FILESYSTEM:
        save_filesystem_command(m, m->command);
        break;
    case D3_IF_FILE:
        file_command(m, m->command, handle);
        break;
    case D3_IF_NVDRV:
        nvdrv_command(m, m->command, handle);
        break;
    case D3_IF_VI_MANAGER:
        vi_manager_command(m, m->command, handle);
        break;
    case D3_IF_VI_APP:
        vi_app_command(m, m->command, handle);
        break;
    case D3_IF_BINDER:
        binder_command(m, m->command);
        break;
    case D3_IF_AOC:
        aoc_command(m, m->command, handle);
        break;
    case D3_IF_ACCOUNT:
        account_command(m, m->command, handle);
        break;
    case D3_IF_HID:
        hid_command(m, m->command, handle);
        break;
    case D3_IF_HID_APPLET_RESOURCE:
        hid_applet_resource_command(m, m->command);
        break;
    case D3_IF_NIFM:
        nifm_command(m, m->command, handle);
        break;
    case D3_IF_NIFM_GENERAL:
        nifm_general_command(m, m->command, handle);
        break;
    case D3_IF_NIFM_REQUEST:
        nifm_request_command(m, m->command);
        break;
    case D3_IF_APM:
        apm_command(m, m->command, handle);
        break;
    case D3_IF_APM_SESSION:
        apm_session_command(m, m->command);
        break;
    case D3_IF_NFP_MANAGER:
        nfp_manager_command(m, m->command, handle);
        break;
    case D3_IF_NFP_USER:
        nfp_user_command(m);
        break;
    case D3_IF_LIBRARY_APPLET_CREATOR:
        library_applet_creator_command(m, m->command, handle);
        break;
    case D3_IF_LIBRARY_APPLET_ACCESSOR:
        library_applet_accessor_command(m, m->command, handle);
        break;
    case D3_IF_STORAGE:
        storage_command(m, m->command, handle);
        break;
    case D3_IF_STORAGE_ACCESSOR:
    case D3_IF_TRANSFER_STORAGE_ACCESSOR:
        storage_accessor_command(m, m->command);
        break;
    case D3_IF_NONE:
        slog("domain %s has no object %u (iface %d)", name, m->domain_object, iface);
        dump_message("no-object", m, handle);
        reply_domain(m, D3_RESULT(121, 1), 1);
        dump_message("no-object-out", m, handle);
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
    g_current_buffer = buffer;
    d3_watch_global(0xc9bba8u, name);
    int kind = d3_handle_kind(handle);
    if (kind != D3_OBJ_SESSION) {
        /* A request on a handle the host never handed out means the guest built
           the handle itself; its frame chain says which stub did, and the handle
           table says what the host had actually allocated by then. */
        slog("SendSyncRequest on handle %#x (%s) kind %d buffer %#" PRIx64, handle, name, kind,
             buffer);
        const uint32_t *words = (const uint32_t *)(uintptr_t)buffer;
        if (buffer)
            d3_service_dump("bad-handle", buffer, words, 0x40);
        d3_trace_guest(which, saved);
        /* nn::hid's applet resource path (sdk+0x250300) reaches its second call
           through this global; its object carries the handle the guest then
           sends to. */
        d3_dump_sdk_global(0xc9bba8u);
        d3_handle_dump();
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
            d3_handle_close(handle);
            saved->x[0] = 0;
            return;
        }
        saved->x[0] = D3_RESULT(11, 2);
        return;
    }
    /* sm: carries the boot's service lookups and is used a handful of times, so
       its requests are dumped in full whatever the loud counter says. */
    const int trace_port = (int)d3_handle_arg(handle);
    const bool trace_sm = trace_port == PORT_SM;
    static unsigned hid_trace_count;
    const bool trace_hid = trace_port == PORT_HID && hid_trace_count++ < 32;
    g_dump_port = trace_port == PORT_HID && !trace_hid ? PORT_NONE : trace_port;
    if (trace_sm || trace_hid)
        dump_message(trace_sm ? "sm-in" : "hid-in", &m, handle);
    if (g_cmif_traces < 64) {
        g_cmif_traces++;
        slog("cmif port=%s cmd=%u tag=%u magic=+%#zx words0..15=%#x %#x %#x %#x %#x %#x %#x %#x "
             "%#x %#x %#x %#x %#x %#x %#x %#x",
             name, m.command, m.w[0] & 0xffffu, m.magic * 4, m.w[0], m.w[1], m.w[2], m.w[3], m.w[4],
             m.w[5], m.w[6],
             m.w[7], m.w[8], m.w[9], m.w[10], m.w[11], m.w[12], m.w[13], m.w[14], m.w[15]);
        d3_service_dump("cmif-in", buffer, m.w, MESSAGE_BYTES);
        d3_trace_guest(name, saved);
    }
    /* A session that was never converted owns no object, so a request naming one
       is really a plain request: answer it in the shape its client reads, not with
       a domain reply the SDK would take for a wrong result word. */
    if (m.domain && m.domain_command == 1 && !domain_any(handle)) {
        const uint32_t object = m.domain_object;
        if (message_plain_at(&m) == 0)
            slog("%s object %u on an unconverted session: read as plain cmd=%u", name, object,
                 m.command);
    }
    repeat_guard(&m, handle);
    if (message_is_control(&m)) {
        control_command(&m, m.command, handle);
        if (trace_sm || trace_hid)
            dump_message(trace_sm ? "sm-out" : "hid-out", &m, handle);
        saved->x[0] = 0;
        return;
    }
    if (m.domain) {
        g_trace_request = 0;
        domain_command(&m, handle);
        if (trace_sm || trace_hid)
            dump_message(trace_sm ? "sm-out" : "hid-out", &m, handle);
        if (g_trace_request)
            d3_trace_guest("domain", saved);
        saved->x[0] = 0;
        return;
    }
    const int port = (int)d3_handle_arg(handle);
    g_trace_request = 0;
    switch (port) {
    case PORT_HID_VIBRATION:
        hid_vibration_command(&m, m.command);
        break;
    case PORT_FRIEND:
        friend_command(&m, m.command, handle, D3_IF_FRIEND_CREATOR);
        break;
    case PORT_AUDIN:
        audin_command(&m, m.command);
        break;
    case PORT_AUDOUT:
        audout_command(&m, m.command, handle);
        break;
    case PORT_AUDIO_OUT:
        audio_out_command(&m, m.command, handle);
        break;
    case PORT_TIME:
        time_service_command(&m, m.command, handle);
        break;
    case PORT_TIME_ZONE:
        unsupported_command(&m, D3_IF_TIME_ZONE, m.command);
        break;
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
    case PORT_SET:
        set_command(&m, m.command);
        break;
    case PORT_NVDRV:
        nvdrv_command(&m, m.command, handle);
        break;
    case PORT_VI_MGR:
        vi_manager_command(&m, m.command, handle);
        break;
    case PORT_VI_APP:
        vi_app_command(&m, m.command, handle);
        break;
    case PORT_BINDER:
        binder_command(&m, m.command);
        break;
    case PORT_HID:
        hid_command(&m, m.command, handle);
        d3_watch_global(0xc9bba8u, "hid-reply");
        d3_watch_global(0xc9bb98u, "hid-reply98");
        break;
    case PORT_HID_APPLET_RESOURCE:
        hid_applet_resource_command(&m, m.command);
        break;
    case PORT_AOC:
        aoc_command(&m, m.command, handle);
        break;
    case PORT_ACCOUNT:
        account_command(&m, m.command, handle);
        break;
    case PORT_APM:
        apm_command(&m, m.command, handle);
        break;
    case PORT_APM_SESSION:
        apm_session_command(&m, m.command);
        break;
    default:
        reply_unsupported(&m, name, m.command, (int)d3_handle_arg(handle));
        break;
    }
    /* The account port answers with the "not initialised" result for every
       command, so its call sites are the ones worth naming while the boot path
       grows: the title's frame chain says which SDK API asked. */
    if (trace_sm || trace_hid)
        dump_message(trace_sm ? "sm-out" : "hid-out", &m, handle);
    if (g_trace_request || port == PORT_ACCOUNT)
        d3_trace_guest(name, saved);
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
