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
         "byte-normalized bool per object, and ConvertCurrentObjectToDomain "
         "returns the actual per-session root id or a real error when full");
    return 0;
}
