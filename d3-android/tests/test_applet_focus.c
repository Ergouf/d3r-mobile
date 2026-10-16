/* Android-native regression test: the per-object focus notification.

   The title's applet loop (guest disassembly 0x33c2d8..0x33c320) calls
   ICommonStateGetter::ReceiveMessage until it reads AppletMessage::FocusStateChanged
   (15); ResultNoMessages (0x680, here D3_RESULT(128, 3)) makes it retry.  The host
   must hand that one message out per freshly opened CommonStateGetter object, so
   this exercises the domain queue and the real SendSyncRequest path by including
   the service layer as one translation unit (the same shape as
   tests/test_stack_memory.c includes host.c).

   Note the domain-vs-plain reply framing: a CommonStateGetter session is a domain,
   so reply_prepare(...,domain=1) writes a four word domain header at the 16 byte
   aligned frame, then the 'SFCO' payload four words later.  The first argument
   word of that payload carries the applet message; the result word precedes it. */
#include "../host/d3_service.c"

#define CHECK(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)

/* For helpers that do not return an int. */
#define REQUIRE(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "FATAL line %d: %s\n", __LINE__, #condition); \
        abort(); \
    } \
} while (0)

/* d3_service.c calls this from send_sync; nothing here needs the guest trace. */
void d3_trace_guest(const char *tag, const d3_saved *saved) {
    (void)tag;
    (void)saved;
}

/* Read back one object's stored SetOutOfFocusSuspendingEnabled value, mirroring
   the bounds and session checks the production setter uses. */
static int object_out_of_focus_suspending(uint32_t session, uint32_t id) {
    if (id == 0 || id > DOMAIN_SLOTS)
        return 0;
    const DomainObject *object = &g_domain[id - 1];
    return object->used && object->session == session ? object->out_of_focus_suspending : 0;
}

/* Read back one object's initialized flag the same way. */
static int object_initialized(uint32_t session, uint32_t id) {
    if (id == 0 || id > DOMAIN_SLOTS)
        return 0;
    const DomainObject *object = &g_domain[id - 1];
    return object->used && object->session == session ? object->initialized : 0;
}

#define MESSAGE_BYTES 0x100

typedef struct {
    uint8_t buffer[MESSAGE_BYTES] __attribute__((aligned(16)));
} RequestBuffer;

/* Where a reply's frame begins: the two header words, then the optional special
   header (with a process id and handle slots when the request carried them),
   rounded up to 16 bytes -- the same walk reply_prepare does. */
static size_t reply_frame(const uint32_t *w) {
    size_t index = 2;
    if (w[1] & 0x80000000u) { /* special header present */
        const uint32_t special = w[2];
        index += 1;
        if (special & 1u)
            index += 2; /* process id */
        index += ((special >> 1) & 0xfu) + ((special >> 5) & 0xfu);
    }
    return (index + 3u) & ~(size_t)3u;
}

/* Read a reply's result word and first out argument.  A domain reply (the common
   state getter session) puts a four word domain header first; a plain reply (the
   ConvertCurrentObjectToDomain control call) does not. */
static void reply_parse(const uint32_t *w, uint32_t *result, uint32_t *outarg) {
    const size_t frame = reply_frame(w);
    size_t payload;
    if (w[frame] == CMIF_OUT) {
        payload = frame; /* plain reply */
    } else {
        REQUIRE(w[frame] == 1u);      /* domain header: one new object id */
        REQUIRE(w[frame + 4] == CMIF_OUT);
        payload = frame + 4;
    }
    *result = w[payload + 2];
    *outarg = w[payload + 4];
}

/* Build a domain SendMessage request for one object.  The domain header word is
   the observed guest value: command 1 (SendMessage) in the low byte, plus the
   CMIF data size the guest reported for that request (0x100001 for the plain
   commands, 0x130001 for the one byte SetOutOfFocusSuspendingEnabled boolean).
   The host only reads the low byte, but the fixture keeps the observed value.
   arg0 lands in the first argument word (w[magic + 4]). */
static void request_build_arg(RequestBuffer *request, uint32_t domain_header, uint32_t command,
                              uint32_t object, uint32_t arg0) {
    memset(request, 0, sizeof *request);
    uint32_t *w = (uint32_t *)request->buffer;
    w[0] = 6;                                   /* hipc SendMessage request */
    w[1] = 0x80000000u | (uint32_t)(16u + 4u);  /* special header, 16 bytes of data */
    w[2] = 0;                                   /* no pid, no copy/move handles */
    w[4] = domain_header;                       /* domain header: cmd 1 in the low byte */
    w[5] = object;                              /* domain object id */
    w[8] = CMIF_IN;
    w[9] = 1;
    w[10] = command;
    w[11] = 0;                                  /* token */
    w[12] = arg0;                               /* first argument word (magic + 4) */
}

/* Send one domain request on a session handle and return the reply's result and
   out argument.  Asserts on the syscall's own status, not just the payload. */
static void request_send_full(uint32_t handle, uint32_t domain_header, uint32_t command,
                              uint32_t object, uint32_t arg0, uint32_t *result,
                              uint32_t *outarg) {
    RequestBuffer request;
    request_build_arg(&request, domain_header, command, object, arg0);
    d3_saved saved = {0};
    saved.x[0] = (uint64_t)(uintptr_t)&request.buffer;
    saved.x[2] = handle;
    d3_svc_send_sync_request_user(&saved);
    REQUIRE(saved.x[0] == 0);
    reply_parse((const uint32_t *)request.buffer, result, outarg);
}

/* The plain command shape (no argument): domain header 0x100001. */
static void request_send(uint32_t handle, uint32_t command, uint32_t object, uint32_t *result,
                         uint32_t *outarg) {
    request_send_full(handle, 0x100001u, command, object, 0, result, outarg);
}

/* One byte boolean argument: domain header 0x130001, the value in the low byte
   of the first argument word.  The extra high byte exercises padding that must
   not be read as part of the value. */
static void request_send_bool(uint32_t handle, uint32_t command, uint32_t object, uint32_t arg0,
                              uint32_t *result, uint32_t *outarg) {
    request_send_full(handle, 0x130001u, command, object, arg0, result, outarg);
}

/* A pctl factory request as the guest sends it: the u64 pid_reserved travels in
   the CMIF payload and the matching process id sits in the special header, so the
   frame moves to word 8 and the CMIF magic to word 12.  The domain header word is
   the observed factory value 0x180001. */
static void request_build_factory(RequestBuffer *request, uint32_t command, uint32_t root) {
    memset(request, 0, sizeof *request);
    uint32_t *w = (uint32_t *)request->buffer;
    w[0] = 6u;
    w[1] = 0x80000000u | 14u;                   /* special header, domain + 24 CMIF bytes */
    w[2] = 1u;                                   /* special header: pid present */
    w[3] = 1u;                                   /* process id, low word */
    w[4] = 0u;                                   /* process id, high word */
    w[8] = 0x00180001u;                          /* domain header: cmd 1, 0x18 data */
    w[9] = root;                                 /* domain object: the pctl root */
    w[12] = CMIF_IN;
    w[13] = 1;
    w[14] = command;
    w[15] = 0;                                   /* token */
    w[16] = 0;                                   /* pid_reserved, low word */
    w[17] = 0;                                   /* pid_reserved, high word */
}

/* Send a factory request on a pctl session and return the new object id. */
static uint32_t pctl_factory(uint32_t handle, uint32_t command, uint32_t root) {
    RequestBuffer request;
    request_build_factory(&request, command, root);
    d3_saved saved = {0};
    saved.x[0] = (uint64_t)(uintptr_t)&request.buffer;
    saved.x[2] = handle;
    d3_svc_send_sync_request_user(&saved);
    REQUIRE(saved.x[0] == 0);
    uint32_t result = 0xdeadbeefu, object = 0xdeadbeefu;
    reply_parse((const uint32_t *)request.buffer, &result, &object);
    REQUIRE(result == 0);        /* the factory call itself succeeded */
    REQUIRE(object != 0);        /* a real new child object */
    REQUIRE(domain_iface(handle, object) == D3_IF_PCTL_SERVICE);
    return object;
}

/* A domain CloseVirtualHandle request in the captured shape: no special header,
   so the 16 byte domain header sits at word 4 with command 2 and the object id,
   and no CMIF payload follows.  type is 6 for SendSyncRequest, 4 for the user
   buffer form.  The tail word carries whatever a previous reply left behind, so
   the host must not mistake it for this request. */
static void request_build_close_tail(RequestBuffer *request, uint32_t type, uint32_t object,
                                     size_t tail_word, uint32_t tail) {
    memset(request, 0, sizeof *request);
    uint32_t *w = (uint32_t *)request->buffer;
    w[0] = type;
    w[1] = 8u; /* raw data includes alignment padding and the domain header */
    w[4] = 2u; /* domain header: command 2 (CloseVirtualHandle), data size 0 */
    w[5] = object;
    w[6] = 0;
    w[7] = 0;
    w[tail_word] = tail; /* stale SFCO/SFCI from the previous reply */
}

static void request_build_close(RequestBuffer *request, uint32_t type, uint32_t object) {
    request_build_close_tail(request, type, object, 12, 0x4f434653u); /* stale SFCO */
}

/* Run one request through the real SendSyncRequest path and return its status. */
static uint64_t request_send_close_system(uint32_t handle, const RequestBuffer *request) {
    d3_saved saved = {0};
    saved.x[0] = handle; /* SendSyncRequest carries the handle in x0, the buffer in tls */
    d3_svc_send_sync_request(&saved, (uint64_t)(uintptr_t)&request->buffer);
    return saved.x[0];
}

/* The SendSyncRequestWithUserBuffer form: the buffer in x0, the handle in x2. */
static uint64_t request_send_close_user(uint32_t handle, const RequestBuffer *request) {
    d3_saved saved = {0};
    saved.x[0] = (uint64_t)(uintptr_t)&request->buffer;
    saved.x[2] = handle;
    d3_svc_send_sync_request_user(&saved);
    return saved.x[0];
}

/* Convert one port session to a domain exactly as the guest does: the port
   handle's SendSyncRequest carries ConvertCurrentObjectToDomain, the service
   answers with the actual root object id it allocated (never a fixed 1), and
   control_command queues port_iface(name) behind it.  The session arg is the
   port kind; control_command picks the iface through port_iface(name). */
static uint32_t session_convert_named(const char *name, int kind, uint32_t *root_out) {
    uint32_t handle = d3_handle_alloc(D3_OBJ_SESSION, name, (uint64_t)kind);
    REQUIRE(handle != 0);

    RequestBuffer request;
    memset(&request, 0, sizeof request);
    uint32_t *w = (uint32_t *)request.buffer;
    w[0] = 5; /* hipc Control, ConvertCurrentObjectToDomain */
    w[1] = 16u + 4u;
    w[4] = CMIF_IN;
    w[5] = 1;
    w[6] = 0; /* command 0 */
    w[7] = 0;

    d3_saved saved = {0};
    saved.x[0] = handle; /* SendSyncRequest carries the handle in x0, the buffer in tls */
    d3_svc_send_sync_request(&saved, (uint64_t)(uintptr_t)&request.buffer);
    REQUIRE(saved.x[0] == 0);
    uint32_t result = 0xdeadbeefu, object = 0;
    reply_parse((const uint32_t *)request.buffer, &result, &object);
    REQUIRE(result == 0);  /* the conversion itself succeeded */
    REQUIRE(object != 0);  /* the host returned a real allocated id, not a fabricated one */
    REQUIRE(domain_iface(handle, object) == port_iface(name));
    *root_out = object;
    return handle;
}

static uint32_t session_convert(uint32_t *root_out) {
    REQUIRE(port_iface("appletOE") == D3_IF_APPLET_OE);
    return session_convert_named("appletOE", PORT_UNKNOWN, root_out);
}

/* Ask IApplicationProxyService (the session's root object) for a fresh
   CommonStateGetter object, the way the guest walks OpenApplicationProxy ->
   GetCommonStateGetter. */
static uint32_t common_state_getter_open(uint32_t session, uint32_t root) {
    uint32_t result = 0xdeadbeefu, proxy = 0;
    request_send(session, 0 /* OpenApplicationProxy */, root, &result, &proxy);
    REQUIRE(result == 0);
    REQUIRE(domain_iface(session, proxy) == D3_IF_APPLICATION_PROXY);
    uint32_t getter = 0;
    request_send(session, 0 /* GetCommonStateGetter */, proxy, &result, &getter);
    REQUIRE(result == 0);
    REQUIRE(domain_iface(session, getter) == D3_IF_COMMON_STATE_GETTER);
    return getter;
}

/* Ask IApplicationProxyService (the session's root object) for a fresh
   SelfController object, the way the guest walks OpenApplicationProxy ->
   GetSelfController. */
static uint32_t self_controller_open(uint32_t session, uint32_t root) {
    uint32_t result = 0xdeadbeefu, proxy = 0;
    request_send(session, 0 /* OpenApplicationProxy */, root, &result, &proxy);
    REQUIRE(result == 0);
    REQUIRE(domain_iface(session, proxy) == D3_IF_APPLICATION_PROXY);
    uint32_t controller = 0;
    request_send(session, 1 /* GetSelfController */, proxy, &result, &controller);
    REQUIRE(result == 0);
    REQUIRE(domain_iface(session, controller) == D3_IF_SELF_CONTROLLER);
    return controller;
}

int main(void) {
    /* Keep every slog inside the compiler's reach from touching /sdcard: the
       first write would mkdir + open the real device log. */
    g_log_tried = 1;
    g_log = -1;

    CHECK(D3_APPLET_MESSAGE_FOCUS_CHANGED == 15);

    uint32_t session_root = 0;
    const uint32_t session = session_convert(&session_root);
    CHECK(session_root != 0); /* the real root id, not a hardcoded 1 */

    /* One object: a focus notification once, then empty for good. */
    uint32_t getter = common_state_getter_open(session, session_root);
    uint32_t result = 0xdeadbeefu, arg = 0;
    request_send(session, 1 /* ReceiveMessage */, getter, &result, &arg);
    CHECK(result == 0);
    CHECK(arg == D3_APPLET_MESSAGE_FOCUS_CHANGED);
    request_send(session, 1, getter, &result, &arg);
    CHECK(result == D3_RESULT(128, 3)); /* ResultNoMessages, the retry signal */
    CHECK(arg == 0);

    /* A second object is independent: it still owes its own notification, and
       consuming it does not touch the first object. */
    uint32_t second = common_state_getter_open(session, session_root);
    CHECK(second != getter);
    request_send(session, 1, second, &result, &arg);
    CHECK(result == 0);
    CHECK(arg == D3_APPLET_MESSAGE_FOCUS_CHANGED);
    request_send(session, 1, second, &result, &arg);
    CHECK(result == D3_RESULT(128, 3));
    request_send(session, 1, getter, &result, &arg); /* first stays consumed */
    CHECK(result == D3_RESULT(128, 3));

    /* A non applet object never gets a queued message. */
    uint32_t proxy = domain_add(session, D3_IF_APPLICATION_PROXY);
    CHECK(proxy != 0 && domain_take_pending(session, proxy) == 0);

    /* GetCurrentFocusState still answers "in focus". */
    request_send(session, 9, getter, &result, &arg);
    CHECK(result == 0);
    CHECK(arg == 1);

    /* A pop from the wrong session leaves the notification for the right one. */
    uint32_t third = common_state_getter_open(session, session_root);
    uint32_t other = d3_handle_alloc(D3_OBJ_SESSION, "appletOE", (uint64_t)PORT_UNKNOWN);
    CHECK(other != 0 && other != session);
    CHECK(domain_take_pending(other, third) == 0);                       /* vacuous pop */
    CHECK(domain_take_pending(session, third) == D3_APPLET_MESSAGE_FOCUS_CHANGED); /* still there */

    /* Closing a still-loaded object drops its unconsumed notification: a fresh
       object is loaded (the controls above showed fresh objects answer 15), yet
       after closing it the same slot holds nothing.  Reusing it queues exactly
       one again. */
    uint32_t fourth = common_state_getter_open(session, session_root);
    CHECK(domain_iface(session, fourth) == D3_IF_COMMON_STATE_GETTER); /* it is live... */
    domain_close(session, fourth);                                    /* ...and unconsumed */
    CHECK(domain_iface(session, fourth) == D3_IF_NONE);
    CHECK(domain_take_pending(session, fourth) == 0); /* close cleared the queued focus */
    uint32_t reused = domain_add(session, D3_IF_COMMON_STATE_GETTER);
    CHECK(reused == fourth); /* the same slot came back */
    CHECK(domain_take_pending(session, reused) == D3_APPLET_MESSAGE_FOCUS_CHANGED);
    CHECK(domain_take_pending(session, reused) == 0);

    /* ---- ISelfController::SetOutOfFocusSuspendingEnabled (cmd 16) ---- */

    uint32_t self = self_controller_open(session, session_root);
    CHECK(object_out_of_focus_suspending(session, self) == 0); /* default off */

    /* false, with clean padding */
    request_send_bool(session, 16, self, 0x00000000u, &result, &arg);
    CHECK(result == 0); /* normal domain success */
    CHECK(object_out_of_focus_suspending(session, self) == 0);

    /* true */
    request_send_bool(session, 16, self, 0x00000001u, &result, &arg);
    CHECK(result == 0);
    CHECK(object_out_of_focus_suspending(session, self) == 1);

    /* the high (padding) bytes must not be read as part of the value: a zero low
       byte stays false even when the rest of the word is all ones */
    request_send_bool(session, 16, self, 0xffffff00u, &result, &arg);
    CHECK(result == 0);
    CHECK(object_out_of_focus_suspending(session, self) == 0);

    /* any non zero low byte is true, again ignoring the padding */
    request_send_bool(session, 16, self, 0xffffff01u, &result, &arg);
    CHECK(result == 0);
    CHECK(object_out_of_focus_suspending(session, self) == 1);

    /* a second SelfController object carries its own value */
    uint32_t self2 = self_controller_open(session, session_root);
    CHECK(self2 != self);
    CHECK(object_out_of_focus_suspending(session, self2) == 0); /* independent */
    CHECK(object_out_of_focus_suspending(session, self) == 1);  /* unchanged */
    request_send_bool(session, 16, self2, 0x00000001u, &result, &arg);
    CHECK(object_out_of_focus_suspending(session, self2) == 1);

    /* a write against a foreign session never reaches the object, and its value
       is unreadable from that session too */
    uint32_t other_session = d3_handle_alloc(D3_OBJ_SESSION, "appletOE", (uint64_t)PORT_UNKNOWN);
    CHECK(other_session != session);
    domain_set_out_of_focus_suspending(other_session, self, 0);
    CHECK(object_out_of_focus_suspending(session, self) == 1); /* unchanged */
    CHECK(object_out_of_focus_suspending(other_session, self) == 0); /* not visible */

    /* close clears the value; the reused slot starts false */
    domain_close(session, self);
    CHECK(object_out_of_focus_suspending(session, self) == 0);
    uint32_t self_reused = domain_add(session, D3_IF_SELF_CONTROLLER);
    CHECK(self_reused == self); /* same slot */
    CHECK(object_out_of_focus_suspending(session, self_reused) == 0);

    /* ---- ConvertCurrentObjectToDomain returns the ACTUAL root id ---- */

    /* Two separate sessions each convert and must land on different root slots.
       Before the fix both answers were a hardcoded 1, so the second session's
       domain_iface(session, 1) resolved to the first session's object (or NONE),
       exactly the boot04 pctl/object 1 collision. */
    uint32_t root2 = 0;
    uint32_t session2 = session_convert_named("appletOE", PORT_UNKNOWN, &root2);
    CHECK(session2 != session);
    CHECK(root2 != 0 && session_root != 0 && root2 != session_root);
    CHECK(domain_iface(session, session_root) == D3_IF_APPLET_OE);
    CHECK(domain_iface(session2, root2) == D3_IF_APPLET_OE);
    CHECK(domain_iface(session, root2) == D3_IF_NONE);      /* not each other's */
    CHECK(domain_iface(session2, session_root) == D3_IF_NONE);

    /* Children opened through each root stay in their own session: the ids
       differ and neither session can resolve the other's child. */
    uint32_t getter1 = common_state_getter_open(session, session_root);
    uint32_t getter2 = common_state_getter_open(session2, root2);
    CHECK(getter1 != getter2);                              /* not both slot 1 */
    CHECK(domain_iface(session, getter1) == D3_IF_COMMON_STATE_GETTER);
    CHECK(domain_iface(session2, getter2) == D3_IF_COMMON_STATE_GETTER);
    CHECK(domain_iface(session, getter2) == D3_IF_NONE);
    CHECK(domain_iface(session2, getter1) == D3_IF_NONE);
    /* each child still owes its own focus notification */
    CHECK(domain_take_pending(session, getter1) == D3_APPLET_MESSAGE_FOCUS_CHANGED);
    CHECK(domain_take_pending(session2, getter2) == D3_APPLET_MESSAGE_FOCUS_CHANGED);

    /* The boot04 pctl session converts to a legal root of its own, distinct from
       the applet roots, and the applet session cannot see it. */
    uint32_t pctl_root = 0;
    uint32_t pctl = session_convert_named("pctl", PORT_UNKNOWN, &pctl_root);
    CHECK(pctl != session && pctl != session2);
    CHECK(pctl_root != 0 && pctl_root != session_root && pctl_root != root2);
    CHECK(domain_iface(pctl, pctl_root) == D3_IF_PCTL);
    CHECK(domain_iface(session, pctl_root) == D3_IF_NONE);
    CHECK(domain_iface(session2, pctl_root) == D3_IF_NONE);

    /* ---- pctl domain bootstrap (factory 0/1 + child Initialize) ---- */

    /* The pctl root is its own object; its factory commands hand out fresh
       service objects, never the root and never a fabricated 0. */
    CHECK(pctl_root != 0);

    /* factory 1 (CreateServiceWithoutInitialize, the HOS >= 4 path): a new object
       is returned but is not initialized until the child Initialize runs. */
    uint32_t svc1 = pctl_factory(pctl, 1, pctl_root);
    CHECK(svc1 != 0 && svc1 != pctl_root);
    CHECK(object_initialized(pctl, svc1) == 0);

    /* factory 0 (CreateService): a fresh object that is already initialized. */
    uint32_t svc0 = pctl_factory(pctl, 0, pctl_root);
    CHECK(svc0 != 0 && svc0 != pctl_root && svc0 != svc1);
    CHECK(object_initialized(pctl, svc0) == 1);

    /* child Initialize (cmd 1) marks only its own object; the factory 1 object
       becomes ready, the others keep their previous state, and the root - not a
       service - is never marked. */
    request_send(pctl, 1 /* Initialize */, svc1, &result, &arg);
    CHECK(result == 0);
    CHECK(object_initialized(pctl, svc1) == 1);
    CHECK(object_initialized(pctl, svc0) == 1);       /* stays ready */
    CHECK(object_initialized(pctl, pctl_root) == 0);  /* the root is not a service */

    /* a later child stays uninitialized until its own Initialize, and a repeat
       Initialize is harmless */
    uint32_t svc2 = pctl_factory(pctl, 1, pctl_root);
    CHECK(svc2 != 0 && svc2 != svc1 && svc2 != svc0);
    CHECK(object_initialized(pctl, svc2) == 0);
    request_send(pctl, 1, svc2, &result, &arg);
    CHECK(object_initialized(pctl, svc2) == 1);
    request_send(pctl, 1, svc2, &result, &arg);
    CHECK(result == 0 && object_initialized(pctl, svc2) == 1);

    /* unknown commands are still refused, never silently accepted */
    request_send(pctl, 1032 /* GetSafetyLevel, unimplemented */, svc1, &result, &arg);
    CHECK(result != 0);
    request_send(pctl, 7 /* not a factory command */, pctl_root, &result, &arg);
    CHECK(result != 0);

    /* close clears the flag; a reused slot starts uninitialized */
    domain_close(pctl, svc1);
    CHECK(object_initialized(pctl, svc1) == 0);
    uint32_t svc_reused = domain_add(pctl, D3_IF_PCTL_SERVICE);
    CHECK(svc_reused == svc1); /* same slot */
    CHECK(object_initialized(pctl, svc_reused) == 0);

    /* ---- domain CloseVirtualHandle (type 4/6, no CMIF payload) ---- */

    /* The captured close shape: no special header, 16 byte domain header at word
       4 with command 2 and the object, and stale reply bytes behind it.  It must
       succeed (0, not the old 0x40b) and release the owning slot. */
    uint32_t close_getter = common_state_getter_open(session, session_root);
    uint32_t sibling = common_state_getter_open(session, session_root);
    CHECK(close_getter != sibling);
    CHECK(domain_iface(session, close_getter) == D3_IF_COMMON_STATE_GETTER); /* unconsumed */
    RequestBuffer close_req;
    request_build_close(&close_req, 6u, close_getter); /* type 6, stale SFCO tail */
    CHECK(request_send_close_system(session, &close_req) == 0);
    CHECK(domain_iface(session, close_getter) == D3_IF_NONE);
    CHECK(domain_take_pending(session, close_getter) == 0); /* queue cleared */
    CHECK(object_initialized(session, close_getter) == 0);
    CHECK(domain_iface(session, sibling) == D3_IF_COMMON_STATE_GETTER); /* sibling intact */
    CHECK(domain_take_pending(session, sibling) == D3_APPLET_MESSAGE_FOCUS_CHANGED);
    /* the freed slot is reusable */
    CHECK(domain_add(session, D3_IF_COMMON_STATE_GETTER) == close_getter);

    /* the same close sent with a stale SFCI tail is still a close, not a message */
    uint32_t close_sfci = common_state_getter_open(session, session_root);
    RequestBuffer close_sfci_req;
    request_build_close_tail(&close_sfci_req, 6u, close_sfci, 12, CMIF_IN);
    CHECK(request_send_close_system(session, &close_sfci_req) == 0);
    CHECK(domain_iface(session, close_sfci) == D3_IF_NONE);

    /* an initialized pctl child, closed through the user buffer form (type 4) */
    uint32_t pctl_child = pctl_factory(pctl, 1, pctl_root);
    request_send(pctl, 1 /* Initialize */, pctl_child, &result, &arg);
    CHECK(object_initialized(pctl, pctl_child) == 1);
    RequestBuffer close_user;
    request_build_close(&close_user, 4u, pctl_child);
    CHECK(request_send_close_user(pctl, &close_user) == 0);
    CHECK(domain_iface(pctl, pctl_child) == D3_IF_NONE);
    CHECK(object_initialized(pctl, pctl_child) == 0);
    CHECK(domain_iface(pctl, pctl_root) == D3_IF_PCTL); /* the root is untouched */

    /* rejected shapes: the object must survive every one of them. */

    /* a domain message with no CMIF payload at all: not close, no SFCI */
    uint32_t keep = common_state_getter_open(session, session_root);
    RequestBuffer no_sfci;
    memset(&no_sfci, 0, sizeof no_sfci);
    uint32_t *nw = (uint32_t *)no_sfci.buffer;
    nw[0] = 6u;
    nw[1] = 8u;
    nw[4] = 0x01000001u; /* domain command 1 (SendMessage), 0x100 data bytes */
    nw[5] = keep;
    CHECK(request_send_close_system(session, &no_sfci) != 0);
    CHECK(domain_iface(session, keep) == D3_IF_COMMON_STATE_GETTER);

    /* a close header that claims a non zero CMIF data size is not a close */
    RequestBuffer short_raw;
    memset(&short_raw, 0, sizeof short_raw);
    uint32_t *sw = (uint32_t *)short_raw.buffer;
    sw[0] = 6u;
    sw[1] = 8u;
    sw[4] = (0x100u << 16) | 2u; /* command 2 but data size 0x100 */
    sw[5] = keep;
    CHECK(request_send_close_system(session, &short_raw) != 0);
    CHECK(domain_iface(session, keep) == D3_IF_COMMON_STATE_GETTER);

    /* a raw count shorter than the header (raw words = 1) is not a close */
    RequestBuffer raw_too_short;
    memset(&raw_too_short, 0, sizeof raw_too_short);
    uint32_t *rw = (uint32_t *)raw_too_short.buffer;
    rw[0] = 6u;
    rw[1] = 1u; /* non zero, so the bare-header fallback does not fire */
    rw[4] = 2u; /* close-like header, but it lies outside the raw data */
    rw[5] = keep;
    CHECK(request_send_close_system(session, &raw_too_short) != 0);
    CHECK(domain_iface(session, keep) == D3_IF_COMMON_STATE_GETTER);

    /* a close-like word behind non empty buffer descriptors is descriptor data,
       not a close header, even with stale reply bytes in the tail */
    RequestBuffer with_desc;
    memset(&with_desc, 0, sizeof with_desc);
    uint32_t *dw = (uint32_t *)with_desc.buffer;
    dw[0] = (uint32_t)(6u | (5u << 16)); /* five buffer descriptors */
    dw[1] = 8u;
    dw[4] = 2u; /* looks like a close header, but it is descriptor data */
    dw[5] = keep;
    dw[12] = 0x4f434653u; /* stale SFCO */
    CHECK(request_send_close_system(session, &with_desc) != 0);
    CHECK(domain_iface(session, keep) == D3_IF_COMMON_STATE_GETTER);

    /* The dangerous fallthrough: a close-shaped header that does NOT qualify,
       with a stale CMIF_IN exactly at frame + 4 (word 8).  Before the fix the
       legacy branch (or full-buffer scan) dispatched it through that stale magic
       into the close path and deleted the object.  It must be refused instead,
       for a non zero data size, a too short raw count, and non empty
       descriptors alike. */
    RequestBuffer stale_at_frame4;
    memset(&stale_at_frame4, 0, sizeof stale_at_frame4);
    uint32_t *cw = (uint32_t *)stale_at_frame4.buffer;
    cw[0] = 6u;
    cw[1] = 8u;
    cw[4] = (0x100u << 16) | 2u; /* cmd 2 but data size 0x100 */
    cw[5] = keep;
    cw[8] = CMIF_IN; /* stale SFCI where the legacy branch looks */
    CHECK(request_send_close_system(session, &stale_at_frame4) != 0);
    CHECK(domain_iface(session, keep) == D3_IF_COMMON_STATE_GETTER);

    RequestBuffer stale_short_raw;
    memset(&stale_short_raw, 0, sizeof stale_short_raw);
    uint32_t *sw2 = (uint32_t *)stale_short_raw.buffer;
    sw2[0] = 6u;
    sw2[1] = 1u; /* raw count too short for the header */
    sw2[4] = 2u;
    sw2[5] = keep;
    sw2[8] = CMIF_IN;
    CHECK(request_send_close_system(session, &stale_short_raw) != 0);
    CHECK(domain_iface(session, keep) == D3_IF_COMMON_STATE_GETTER);

    RequestBuffer stale_desc;
    memset(&stale_desc, 0, sizeof stale_desc);
    uint32_t *sw3 = (uint32_t *)stale_desc.buffer;
    sw3[0] = (uint32_t)(6u | (1u << 16)); /* one buffer descriptor */
    sw3[1] = 8u;
    sw3[4] = 2u;
    sw3[5] = keep;
    sw3[8] = CMIF_IN;
    CHECK(request_send_close_system(session, &stale_desc) != 0);
    CHECK(domain_iface(session, keep) == D3_IF_COMMON_STATE_GETTER);

    /* a raw count that runs past the buffer is refused the same way */
    RequestBuffer huge_raw;
    memset(&huge_raw, 0, sizeof huge_raw);
    uint32_t *hw = (uint32_t *)huge_raw.buffer;
    hw[0] = 6u;
    hw[1] = 0x3ffu; /* raw_end well beyond MESSAGE_WORDS */
    hw[4] = 2u;
    hw[5] = keep;
    CHECK(request_send_close_system(session, &huge_raw) != 0);
    CHECK(domain_iface(session, keep) == D3_IF_COMMON_STATE_GETTER);

    /* a valid close aimed at another session's object reports success but frees
       nothing: the object stays usable by its owning session */
    uint32_t foreign = common_state_getter_open(session2, root2);
    RequestBuffer wrong_session;
    request_build_close(&wrong_session, 6u, foreign);
    CHECK(request_send_close_system(session, &wrong_session) == 0);
    CHECK(domain_iface(session2, foreign) == D3_IF_COMMON_STATE_GETTER);
    CHECK(domain_take_pending(session2, foreign) == D3_APPLET_MESSAGE_FOCUS_CHANGED);

    /* ---- ConvertCurrentObjectToDomain when the table is full ---- */

    /* No free slot: the conversion must report an error and hand back no object
       id at all, never a fabricated one. */
    for (uint32_t index = 0; index <= DOMAIN_SLOTS; index++) {
        if (domain_add(session, D3_IF_PCTL) == 0)
            break;
    }

    uint32_t fresh = d3_handle_alloc(D3_OBJ_SESSION, "appletOE", (uint64_t)PORT_UNKNOWN);
    CHECK(fresh != 0);
    RequestBuffer full_request;
    memset(&full_request, 0, sizeof full_request);
    uint32_t *fw = (uint32_t *)full_request.buffer;
    fw[0] = 5;
    fw[1] = 16u + 4u;
    fw[4] = CMIF_IN;
    fw[5] = 1;
    fw[6] = 0;
    fw[7] = 0;
    d3_saved full_saved = {0};
    full_saved.x[0] = fresh;
    d3_svc_send_sync_request(&full_saved, (uint64_t)(uintptr_t)&full_request.buffer);
    CHECK(full_saved.x[0] == 0);
    uint32_t full_result = 0, full_object = 0xdeadbeefu;
    reply_parse((const uint32_t *)full_request.buffer, &full_result, &full_object);
    CHECK(full_result == D3_RESULT(21, 7)); /* a real error, not success */
    CHECK(full_object == 0);                /* no fabricated object id */
    CHECK(domain_iface(fresh, 1) == D3_IF_NONE); /* id 1 does not exist for fresh */

    puts("PASS: applet focus notification is one message per object, objects are "
         "independent, the queue empties after consume, wrong-session pops are "
         "vacuous, close/reset clears it, SetOutOfFocusSuspendingEnabled stores a "
         "byte-normalized bool per object, ConvertCurrentObjectToDomain "
         "returns the actual per-session root id or a real error when full, "
         "pctl factory 0/1 with child Initialize manages per-object state, and "
         "domain CloseVirtualHandle is recognized without a CMIF payload while "
         "malformed shapes are refused");
    return 0;
}
