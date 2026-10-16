/* Android-native regression test: the time:u service's root domain object and
   its ITimeZoneService child.

   Contract this test pins (coordinator owns the service side):

     1. ConvertCurrentObjectToDomain on a `time:u` session must give a root object
        whose iface is NOT D3_IF_NONE.  On device the recovered host answered
        `control time:u ConvertCurrentObjectToDomain -> object 13 (0)` and the next
        request was rejected as `domain time:u has no object 13 (iface 0)` (see
        analysis/apk-config02-logcat.txt lines 876/887).  The root must carry the
        new D3_IF_TIME tag instead.

     2. Domain root object, CMIF command 3 with no arguments, must hand back
        EXACTLY one valid ITimeZoneService object: a fresh domain id that differs
        from the root and resolves to D3_IF_TIME_ZONE.  Two calls hand back two
        distinct objects.

     3. Two time:u sessions are isolated: each root's child id is usable only from
        its own session, a foreign id resolves to D3_IF_NONE and a SendMessage to
        it is refused, and closing a child makes its id invalid and unusable.

     4. When the domain table is exhausted, command 3 reports an explicit non-zero
        error and hands back no object id at all (out-object count 0, no fabricated
        id) -- never a success or a bogus id.

     5. Unknown commands on the root (D3_IF_TIME) and on the child
        (D3_IF_TIME_ZONE) are refused with a non-zero result, never a fake success.

     Non-domain note: command 3 on a `time:u` session that has NOT been converted
     to a domain must return a MOVE SESSION handle (an ITimeZoneService session in
     the HIPC handle slot), not a domain object id.

   Landed implementation this pins (coordinator):
     - d3_service_names.h enum append: D3_IF_TIME = 22, D3_IF_TIME_ZONE = 23;
       PORT_TIME / PORT_TIME_ZONE appended to the port enum.
     - port_iface()/port_kind(): "time:u" -> D3_IF_TIME / PORT_TIME.
     - domain_command(): D3_IF_TIME -> time_service_command(); D3_IF_TIME_ZONE is
       still unsupported, so every child command is refused.
     - root cmd 3 (domain): domain_add(session, D3_IF_TIME_ZONE) then
       reply_domain_object() (exactly one out object); table-full -> reply_domain()
       with a non-zero result and no out object.
     - root cmd 3 (non-domain): a move session handle in the HIPC handle slot with
       no extra payload word (reply_prepare(m, 1, 0, 0) + the move-handle slot).
     - reply_prepare()'s domain out-object count defaults to 0; only
       reply_domain_object() sets it to 1.
     - d3_handle_close(session) releases every domain object of that session, and a
       bare HIPC close also closes the handle.

   This test #includes the service layer as one translation unit (the same shape
   as tests/test_applet_focus.c and tests/test_set_service.c) so it drives the real
   SendSyncRequestWithUserBuffer path and the real domain dispatch.  It is written
   to compile in the Android test build but is not compiled or run by this task. */

#include "../host/d3_service.c"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* d3_service.c calls this from send_sync; nothing here needs the guest trace. */
void d3_trace_guest(const char *tag, const d3_saved *saved) {
    (void)tag;
    (void)saved;
}

#define CHECK(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)

/* For helpers that cannot return an int. */
#define REQUIRE(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "FATAL line %d: %s\n", __LINE__, #condition); \
        abort(); \
    } \
} while (0)

/* The same 16 byte aligned HIPC TLS buffer the guest posts requests in. */
typedef struct { uint32_t w[MESSAGE_WORDS] __attribute__((aligned(16))); } Buffer;

/* ---- reply walk (mirrors reply_prepare / the other tests) ---- */

/* Where a reply's frame begins: the two header words, then the optional special
   header (with a process id and handle slots when the request carried them),
   rounded up to 16 bytes. */
static size_t reply_frame(const uint32_t *w) {
    size_t index = 2;
    if (w[1] & 0x80000000u) {
        const uint32_t special = w[2];
        index += 1;
        if (special & 1u)
            index += 2;
        index += ((special >> 1) & 0xfu) + ((special >> 5) & 0xfu);
    }
    return (index + 3u) & ~(size_t)3u;
}

typedef struct {
    uint32_t result;       /* CMIF result word */
    uint32_t out0;         /* first out argument (payload + 4) */
    int special;           /* the reply carried a special header */
    uint32_t move_handles; /* moved handles in the special header */
    uint32_t handle;       /* the first handle slot value, if any */
    int domain_reply;      /* the frame word was a domain header, not CMIF_OUT */
    uint32_t domain_word;  /* the raw frame word (the codebase's domain header) */
} Reply;

/* Parse a reply the way the guest client does.  A plain reply puts CMIF_OUT on
   the frame; a domain reply puts a four word domain header there first. */
static void reply_read(const uint32_t *w, Reply *r) {
    memset(r, 0, sizeof *r);
    const size_t frame = reply_frame(w);
    r->special = (w[1] >> 31) & 1u;
    r->domain_word = w[frame];
    size_t slot = 2;
    if (r->special) {
        const uint32_t special = w[2];
        r->move_handles = (special >> 5) & 0xfu;
        slot += 1;
        if (special & 1u)
            slot += 2;
    }
    if (r->special && r->move_handles > 0)
        r->handle = w[slot];
    size_t payload;
    if (w[frame] == CMIF_OUT) {
        r->domain_reply = 0; /* plain reply */
        payload = frame;
    } else {
        r->domain_reply = 1; /* domain header: reply_domain(_object) shape */
        payload = frame + 4;
    }
    r->result = w[payload + 2];
    r->out0 = w[payload + 4];
}

/* ---- request builders ---- */

/* A domain SendMessage request for one object, zero arguments.  The domain
   header word is the value the guest posts (cmd 1, no objects, 16 data bytes);
   arg0 lands in the first argument word. */
static void build_domain(Buffer *b, uint32_t command, uint32_t object, uint32_t arg0) {
    memset(b, 0, sizeof *b);
    b->w[0] = 6;                                   /* hipc SendMessage request */
    b->w[1] = 0x80000000u | (uint32_t)(16u + 4u);  /* special header, 16 data bytes */
    b->w[2] = 0;                                   /* no pid, no copy/move handles */
    b->w[4] = 0x00100001u;                         /* domain header: cmd 1, 0 objects, 0x10 data */
    b->w[5] = object;                              /* domain object id */
    b->w[8] = CMIF_IN;
    b->w[9] = 1;
    b->w[10] = command;
    b->w[11] = 0;                                  /* token */
    b->w[12] = arg0;                               /* first argument word */
}

/* A hipc Control request (ConvertCurrentObjectToDomain is command 0). */
static void build_control(Buffer *b, uint32_t command) {
    memset(b, 0, sizeof *b);
    b->w[0] = 5;             /* hipc Control */
    b->w[1] = 16u + 4u;
    b->w[4] = CMIF_IN;
    b->w[5] = 1;
    b->w[6] = command;
    b->w[7] = 0;
}

/* A plain (non domain) service request: no special header, so the two word
   header block puts the CMIF frame at word 4 and arg0 at word 8. */
static void build_plain(Buffer *b, uint32_t command, uint32_t arg0) {
    memset(b, 0, sizeof *b);
    b->w[0] = 6;      /* hipc SendMessage request */
    b->w[1] = 9u;     /* raw data: header + CMIF payload + argument word */
    b->w[4] = CMIF_IN;
    b->w[5] = 1;
    b->w[6] = command;
    b->w[7] = 0;      /* token */
    b->w[8] = arg0;
}

/* A domain CloseVirtualHandle request: command 2 with no CMIF payload.  type is
   6 for the plain SendSyncRequest form, 4 for the user buffer form. */
static void build_close(Buffer *b, uint32_t type, uint32_t object) {
    memset(b, 0, sizeof *b);
    b->w[0] = type;
    b->w[1] = 8u;     /* raw data includes the 16 byte domain header */
    b->w[4] = 2u;     /* domain header: command 2, no data */
    b->w[5] = object;
}

/* ---- send helpers ---- */

/* Run one already built request through the real user-buffer dispatch and parse
   its reply.  A non-zero syscall status is a host infra fault, so it aborts. */
static void send_buffer(uint32_t handle, Buffer *b, Reply *r) {
    d3_saved saved = {0};
    saved.x[0] = (uint64_t)(uintptr_t)b->w;
    saved.x[2] = handle;
    d3_svc_send_sync_request_user(&saved);
    REQUIRE(saved.x[0] == 0);
    reply_read(b->w, r);
}

static void domain_send(uint32_t handle, uint32_t command, uint32_t object, uint32_t arg0,
                        Reply *r) {
    Buffer b;
    build_domain(&b, command, object, arg0);
    send_buffer(handle, &b, r);
}

/* Convert one time:u session to a domain and return the handle plus the actual
   root object id the host allocated (never a hardcoded 1). */
static uint32_t session_convert(const char *name, uint32_t *root_out) {
    uint32_t handle = d3_handle_alloc(D3_OBJ_SESSION, name, (uint64_t)PORT_UNKNOWN);
    REQUIRE(handle != 0);
    Buffer b;
    build_control(&b, 0); /* ConvertCurrentObjectToDomain */
    Reply r;
    send_buffer(handle, &b, &r);
    REQUIRE(r.result == 0);
    REQUIRE(r.out0 != 0);
    *root_out = r.out0;
    return handle;
}

int main(void) {
    /* Keep every slog inside the compiler's reach from touching /sdcard. */
    g_log_tried = 1;
    g_log = -1;

    Reply r;

    /* ---- 1. Convert time:u gives a root whose iface is not D3_IF_NONE ---- */

    CHECK(D3_IF_TIME != D3_IF_NONE);
    CHECK(D3_IF_TIME_ZONE != D3_IF_NONE);
    CHECK(D3_IF_TIME_ZONE != D3_IF_TIME);
    CHECK(port_iface("time:u") == D3_IF_TIME); /* the mapping the fix adds */
    CHECK(D3_IF_TIME == 22);                   /* value appended by the fix */
    CHECK(D3_IF_TIME_ZONE == 23);

    uint32_t root = 0;
    uint32_t session = session_convert("time:u", &root);
    CHECK(root != 0);                              /* a real id, not a hardcoded 1 */
    CHECK(domain_iface(session, root) != D3_IF_NONE);
    CHECK(domain_iface(session, root) == D3_IF_TIME);

    /* ---- 2. root cmd 3 (no arguments) -> exactly one ITimeZoneService ---- */

    /* A domain success reply hands out one object: the frame carries the domain
       header (the codebase marks "one new object id" with a frame word of 1) and
       the id sits in the first out argument. */
    domain_send(session, 3, root, 0, &r);
    CHECK(r.result == 0);
    CHECK(r.domain_reply);
    CHECK(r.domain_word == 1);                 /* one new object id, and CMIF_OUT behind it */
    CHECK(r.out0 != 0);                        /* a real allocated id */
    CHECK(r.out0 != root);                     /* distinct from the root */
    CHECK(domain_iface(session, r.out0) == D3_IF_TIME_ZONE);
    CHECK(domain_iface(session, root) == D3_IF_TIME); /* the root is untouched */
    uint32_t zone = r.out0;

    /* A second call hands back a different child, not the same cached one. */
    domain_send(session, 3, root, 0, &r);
    CHECK(r.result == 0 && r.out0 != 0);
    CHECK(r.out0 != root && r.out0 != zone);
    CHECK(domain_iface(session, r.out0) == D3_IF_TIME_ZONE);
    uint32_t zone_b = r.out0;

    /* ---- 3. two sessions are isolated; foreign ids are unreachable; close ---- */

    uint32_t root2 = 0;
    uint32_t session2 = session_convert("time:u", &root2);
    CHECK(session2 != session);
    CHECK(root2 != root);
    CHECK(domain_iface(session2, root2) == D3_IF_TIME);

    domain_send(session2, 3, root2, 0, &r);
    CHECK(r.result == 0 && r.out0 != 0);
    uint32_t zone2 = r.out0;
    CHECK(zone2 != zone && zone2 != zone_b && zone2 != root2);
    CHECK(domain_iface(session2, zone2) == D3_IF_TIME_ZONE);

    /* Each session can resolve only its own objects. */
    CHECK(domain_iface(session, zone) == D3_IF_TIME_ZONE);
    CHECK(domain_iface(session2, zone2) == D3_IF_TIME_ZONE);
    CHECK(domain_iface(session, zone2) == D3_IF_NONE);
    CHECK(domain_iface(session2, zone) == D3_IF_NONE);

    /* A SendMessage to a foreign object id is refused, not silently answered. */
    domain_send(session, 3, zone2, 0, &r);
    CHECK(r.result != 0);

    /* Closing the child frees its id: it stops resolving and further use is
       refused.  The sibling session's child is untouched. */
    Buffer close;
    build_close(&close, 6u, zone);
    send_buffer(session, &close, &r);       /* CloseVirtualHandle succeeds */
    CHECK(r.result == 0);
    CHECK(domain_iface(session, zone) == D3_IF_NONE);
    domain_send(session, 3, zone, 0, &r);   /* the closed id is no longer usable */
    CHECK(r.result != 0);
    CHECK(domain_iface(session2, zone2) == D3_IF_TIME_ZONE);
    CHECK(domain_iface(session, root) == D3_IF_TIME); /* the root survives a child close */

    /* ---- 5. unknown root / child commands are refused, never fake success ---- */

    /* (done before the table is filled so a live child is available) */
    uint32_t root5 = 0;
    uint32_t session5 = session_convert("time:u", &root5);
    domain_send(session5, 3, root5, 0, &r);
    CHECK(r.result == 0 && r.out0 != 0);
    uint32_t zone5 = r.out0;

    domain_send(session5, 0x7fu, root5, 0, &r);  /* unknown root command */
    CHECK(r.result != 0);
    domain_send(session5, 0x7fu, zone5, 0, &r);  /* unknown child command */
    CHECK(r.result != 0);
    /* The refused commands left the objects usable. */
    CHECK(domain_iface(session5, root5) == D3_IF_TIME);
    CHECK(domain_iface(session5, zone5) == D3_IF_TIME_ZONE);

    /* ---- non-domain session: cmd 3 returns a MOVE SESSION handle, not a domain id ---- */

    uint32_t plain_session = d3_handle_alloc(D3_OBJ_SESSION, "time:u", (uint64_t)PORT_TIME);
    CHECK(plain_session != 0);
    CHECK(plain_session != session && plain_session != session2);
    CHECK(d3_handle_arg(plain_session) == PORT_TIME); /* the kind sm:GetService assigns */

    Buffer plain_req;
    build_plain(&plain_req, 3, 0);
    send_buffer(plain_session, &plain_req, &r);
    CHECK(r.result == 0);                        /* the method itself succeeds */
    CHECK(!r.domain_reply);                      /* NOT a domain object reply */
    CHECK(r.special && r.move_handles == 1);     /* one moved handle, in the handle slot */
    CHECK(r.handle != 0);                        /* a real session handle */
    CHECK(d3_handle_kind(r.handle) == D3_OBJ_SESSION);
    CHECK(r.handle != plain_session);            /* a new child session, not the caller */
    CHECK(r.out0 == 0);                          /* no extra payload word: the handle is the only out */

    /* ---- whole-session close: d3_handle_close frees every slot of the session ---- */

    uint32_t root_w = 0;
    uint32_t session_w = session_convert("time:u", &root_w);
    domain_send(session_w, 3, root_w, 0, &r);
    CHECK(r.result == 0 && r.out0 != 0);
    uint32_t zone_w = r.out0;
    CHECK(domain_iface(session_w, root_w) == D3_IF_TIME);
    CHECK(domain_iface(session_w, zone_w) == D3_IF_TIME_ZONE);

    CHECK(d3_handle_close(session_w) == 0);      /* the session handle closes cleanly */
    /* Every domain object of that session is gone, root and child alike. */
    CHECK(domain_iface(session_w, root_w) == D3_IF_NONE);
    CHECK(domain_iface(session_w, zone_w) == D3_IF_NONE);
    /* A freed slot is available again: the session's slots were released. */
    CHECK(domain_add(session_w, D3_IF_TIME_ZONE) != 0);

    /* ---- bare HIPC close (w0 == 2, w1 == 0): the handle closes too ---- */

    uint32_t root_b = 0;
    uint32_t session_b = session_convert("time:u", &root_b);
    domain_send(session_b, 3, root_b, 0, &r);
    CHECK(r.result == 0 && r.out0 != 0);
    uint32_t zone_bc = r.out0;
    CHECK(domain_iface(session_b, root_b) == D3_IF_TIME);
    CHECK(domain_iface(session_b, zone_bc) == D3_IF_TIME_ZONE);

    Buffer bare;
    memset(&bare, 0, sizeof bare);
    bare.w[0] = 2u;   /* hipc Close */
    bare.w[1] = 0u;
    d3_saved bare_saved = {0};
    bare_saved.x[0] = (uint64_t)(uintptr_t)bare.w;
    bare_saved.x[2] = session_b;
    d3_svc_send_sync_request_user(&bare_saved);
    CHECK(bare_saved.x[0] == 0);                 /* bare close answered with an empty reply */
    /* The bare close released the session's domain objects too. */
    CHECK(domain_iface(session_b, root_b) == D3_IF_NONE);
    CHECK(domain_iface(session_b, zone_bc) == D3_IF_NONE);

    /* ---- 4. domain table full: cmd 3 reports a real error, no fabricated id ----
       Done last so the exhausted table does not disturb the sessions above. */

    uint32_t root4 = 0;
    uint32_t session4 = session_convert("time:u", &root4);

    /* Exhaust every remaining domain slot.  The root already holds one, so once
       domain_add returns 0 the table is full and the next cmd 3 cannot allocate
       its child. */
    for (uint32_t index = 0; index <= DOMAIN_SLOTS; index++) {
        if (domain_add(session4, D3_IF_PCTL) == 0)
            break;
    }

    domain_send(session4, 3, root4, 0, &r);
    CHECK(r.result != 0);                       /* an explicit error, never success */
    CHECK(r.domain_reply);                      /* still a well-formed domain reply */
    /* Out-object count zero: the reply carries no id, so nothing was fabricated
       (the observable form of "out object count == 0" in this framing). */
    CHECK(r.out0 == 0);
    CHECK(domain_iface(session4, root4) == D3_IF_TIME); /* the root is still there */

    puts("PASS: time:u converts to a D3_IF_TIME root (not iface 0), domain root "
         "cmd 3 hands out exactly one D3_IF_TIME_ZONE child distinct from the root, "
         "two sessions stay isolated with foreign ids unreachable and closed ids "
         "invalid, an exhausted domain table makes cmd 3 return a non-zero error "
         "with no fabricated object id, unknown root/child commands are refused, "
         "and a non-domain session's cmd 3 returns a move session handle");
    return 0;
}
