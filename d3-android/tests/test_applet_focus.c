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

/* Convert the appletOE session to a domain exactly as the guest does: the port
   handle's SendSyncRequest carries ConvertCurrentObjectToDomain, the service
   answers with the initial object id (1), and control_command queues the applet
   interfaces behind it.  The session arg is the port kind (appletOE is unknown
   to port_kind); control_command picks the iface through port_iface(name). */
static uint32_t session_convert(void) {
    uint32_t handle = d3_handle_alloc(D3_OBJ_SESSION, "appletOE", (uint64_t)PORT_UNKNOWN);
    REQUIRE(handle != 0);
    REQUIRE((int)PORT_UNKNOWN == (int)d3_handle_arg(handle));
    REQUIRE(port_iface("appletOE") == D3_IF_APPLET_OE);

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
    REQUIRE(result == 0);
    REQUIRE(object == 1u); /* first domain slot */
    REQUIRE(domain_iface(handle, object) == D3_IF_APPLET_OE);
    return handle;
}

/* Ask IApplicationProxyService (object 1) for a fresh CommonStateGetter object,
   the way the guest walks OpenApplicationProxy -> GetCommonStateGetter. */
static uint32_t common_state_getter_open(uint32_t session) {
    uint32_t result = 0xdeadbeefu, proxy = 0;
    request_send(session, 0 /* OpenApplicationProxy */, 1, &result, &proxy);
    REQUIRE(result == 0);
    REQUIRE(domain_iface(session, proxy) == D3_IF_APPLICATION_PROXY);
    uint32_t getter = 0;
    request_send(session, 0 /* GetCommonStateGetter */, proxy, &result, &getter);
    REQUIRE(result == 0);
    REQUIRE(domain_iface(session, getter) == D3_IF_COMMON_STATE_GETTER);
    return getter;
}

/* Ask IApplicationProxyService (object 1) for a fresh SelfController object, the
   way the guest walks OpenApplicationProxy -> GetSelfController. */
static uint32_t self_controller_open(uint32_t session) {
    uint32_t result = 0xdeadbeefu, proxy = 0;
    request_send(session, 0 /* OpenApplicationProxy */, 1, &result, &proxy);
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

    const uint32_t session = session_convert();

    /* One object: a focus notification once, then empty for good. */
    uint32_t getter = common_state_getter_open(session);
    uint32_t result = 0xdeadbeefu, arg = 0;
    request_send(session, 1 /* ReceiveMessage */, getter, &result, &arg);
    CHECK(result == 0);
    CHECK(arg == D3_APPLET_MESSAGE_FOCUS_CHANGED);
    request_send(session, 1, getter, &result, &arg);
    CHECK(result == D3_RESULT(128, 3)); /* ResultNoMessages, the retry signal */
    CHECK(arg == 0);

    /* A second object is independent: it still owes its own notification, and
       consuming it does not touch the first object. */
    uint32_t second = common_state_getter_open(session);
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
    uint32_t third = common_state_getter_open(session);
    uint32_t other = d3_handle_alloc(D3_OBJ_SESSION, "appletOE", (uint64_t)PORT_UNKNOWN);
    CHECK(other != 0 && other != session);
    CHECK(domain_take_pending(other, third) == 0);                       /* vacuous pop */
    CHECK(domain_take_pending(session, third) == D3_APPLET_MESSAGE_FOCUS_CHANGED); /* still there */

    /* Closing a still-loaded object drops its unconsumed notification: a fresh
       object is loaded (the controls above showed fresh objects answer 15), yet
       after closing it the same slot holds nothing.  Reusing it queues exactly
       one again. */
    uint32_t fourth = common_state_getter_open(session);
    CHECK(domain_iface(session, fourth) == D3_IF_COMMON_STATE_GETTER); /* it is live... */
    domain_close(session, fourth);                                    /* ...and unconsumed */
    CHECK(domain_iface(session, fourth) == D3_IF_NONE);
    CHECK(domain_take_pending(session, fourth) == 0); /* close cleared the queued focus */
    uint32_t reused = domain_add(session, D3_IF_COMMON_STATE_GETTER);
    CHECK(reused == fourth); /* the same slot came back */
    CHECK(domain_take_pending(session, reused) == D3_APPLET_MESSAGE_FOCUS_CHANGED);
    CHECK(domain_take_pending(session, reused) == 0);

    /* ---- ISelfController::SetOutOfFocusSuspendingEnabled (cmd 16) ---- */

    uint32_t self = self_controller_open(session);
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
    uint32_t self2 = self_controller_open(session);
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

    puts("PASS: applet focus notification is one message per object, objects are "
         "independent, the queue empties after consume, wrong-session pops are "
         "vacuous, close/reset clears it, and SetOutOfFocusSuspendingEnabled "
         "stores a byte-normalized bool per object with reset");
    return 0;
}
