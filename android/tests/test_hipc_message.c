/* Android-native regression test: the HIPC request layout walker (message_parse
   in the service layer).

   The walker must count the header block the way the public HIPC layout does:
   two words of header, then the optional special header, then the process id,
   then the copy and move handle slots, then the buffer descriptors -- X (static)
   two words each, A/B/W three each -- and the CMIF payload frame on the next 16
   byte boundary after that block.  The frame and the CMIF payload must fall
   inside the declared raw data (w1 bits 0..9), the SFCI magic must sit exactly
   at the frame, and it must never be found by scanning the rest of the buffer.

   The subject is a private (static) function, so this includes the service layer
   as one translation unit -- the same shape as tests/test_applet_focus.c and
   tests/test_stack_memory.c -- and drives message_parse directly. */
#include "../host/d3_service.c"

#include <stdio.h>
#include <stdlib.h>

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

/* The domain message header packs cmd:u8, objects:u8 and data_size:u16. */
#define DOMAIN_HEADER(command, objects, bytes) \
    (((uint32_t)(bytes) << 16) | ((uint32_t)(objects) << 8) | (uint32_t)(command))

/* The same 16 byte aligned HIPC TLS buffer the guest posts requests in. */
typedef struct { uint32_t w[MESSAGE_WORDS] __attribute__((aligned(16))); } Buffer;

static void buffer_reset(Buffer *b) {
    memset(b->w, 0, sizeof b->w);
}

/* The public header walk, written out independently of the parser under test:
   header, special header, process id, copy then move handle slots, X descriptors
   (two words) and A/B/W descriptors (three words).  `handles` is the special
   header word when one is present. */
static size_t header_index(uint32_t counts, int special, int pid, uint32_t handles) {
    size_t index = special ? (size_t)(3 + (pid ? 2 : 0)) : 2;
    if (special)
        index += ((handles >> 1) & 0xfu) + ((handles >> 5) & 0xfu);
    index += 2u * (counts & 0xfu);
    index += 3u * (((counts >> 4) & 0xfu) + ((counts >> 8) & 0xfu) + ((counts >> 12) & 0xfu));
    return index;
}

static size_t expected_frame(uint32_t counts, int special, int pid, uint32_t handles) {
    return (header_index(counts, special, pid, handles) + 3u) & ~(size_t)3u;
}

/* Build a well formed request whose header shape is fixed by w0/w1/w2 and place
   the CMIF payload at the frame the public layout implies: a plain request puts
   the magic at the frame, a domain SendMessage puts a four word domain header
   there and the magic at frame + 4.  The raw count is sized to cover the whole
   message so only the shape under test is exercised. */
static size_t build_request(Buffer *b, uint32_t w0, uint32_t w1, uint32_t w2, int domain,
                            uint32_t domain_object, uint32_t command) {
    buffer_reset(b);
    const int special = (w1 >> 31) != 0;
    const int pid = special && (w2 & 1u);
    const uint32_t counts = w0 >> 16;
    const size_t index = header_index(counts, special, pid, w2);
    const size_t frame = expected_frame(counts, special, pid, w2);
    b->w[0] = w0;
    b->w[1] = (special ? 0x80000000u : 0u) | (uint32_t)(MESSAGE_WORDS - index);
    if (special)
        b->w[2] = w2;
    size_t magic = frame;
    if (domain) {
        b->w[frame] = DOMAIN_HEADER(1, 0, 16); /* SendMessage, no objects, 16 data bytes */
        b->w[frame + 1] = domain_object;
        magic = frame + 4;
    }
    b->w[magic] = CMIF_IN;
    b->w[magic + 1] = 1u; /* CMIF version */
    b->w[magic + 2] = command;
    b->w[magic + 3] = 0u; /* token */
    b->w[magic + 4] = 0xaaaaaaaau; /* first argument word */
    return frame;
}

/* Parse one buffer and require the walker accepted it. */
static void require_parsed(const Buffer *b, Message *m, int line) {
    if (message_parse(m, (uint64_t)(uintptr_t)b->w) != 0) {
        fprintf(stderr, "FAIL line %d: %#x %#x did not parse\n", line, b->w[0], b->w[1]);
        abort();
    }
}

/* A plain (non domain) request: the magic lands on the 16 byte frame the header
   block implies, with no domain header before it. */
static int plain_request_case(Buffer *b, uint32_t w0, uint32_t command) {
    const size_t frame = build_request(b, w0, 0u, 0u, 0, 0u, command);
    Message m;
    require_parsed(b, &m, __LINE__);
    CHECK(m.domain == 0);
    CHECK(m.frame == frame);
    CHECK(m.magic == frame);
    CHECK(m.command == command);
    return 0;
}

int main(void) {
    /* Keep every slog inside the compiler's reach from touching /sdcard. */
    g_log_tried = 1;
    g_log = -1;

    /* ---- the captured fault: one receive buffer descriptor ---- */

    /* A boot request with a single receive buffer descriptor (w0 descriptor
       count 0x0100 = one A/B/W descriptor, three words).  The earlier walker
       counted no descriptors, so the frame landed at word 4, word 4's low byte
       was read as a domain header and the request was misread as a domain
       message.  The correct walk puts the frame at word 8, where the real SFCI
       magic sits, so it is a PLAIN request (domain == 0), magic == 8 and the
       command is word 10. */
    Buffer fault;
    buffer_reset(&fault);
    fault.w[0] = 0x01000006u; /* type 6, descriptor count 0x0100 (one B descriptor) */
    fault.w[1] = 8u;          /* raw data: header + descriptor + pad + CMIF payload */
    fault.w[2] = 0x00000200u; /* descriptor word */
    fault.w[3] = 0xe766d16cu; /* descriptor word */
    fault.w[4] = 0x1000001cu; /* descriptor word */
    fault.w[5] = 1u;
    fault.w[8] = CMIF_IN;
    fault.w[9] = 1u;
    fault.w[10] = 5u;
    fault.w[11] = 0u;
    fault.w[12] = 0u;
    Message fm;
    CHECK(message_parse(&fm, (uint64_t)(uintptr_t)fault.w) == 0);
    CHECK(fm.domain == 0);
    CHECK(fm.frame == expected_frame(0x0100u, 0, 0, 0)); /* == 8 */
    CHECK(fm.frame == 8);
    CHECK(fm.magic == 8);
    CHECK(fm.command == 5);

    /* ---- well formed shapes ---- */

    /* no descriptors */
    Buffer b;
    CHECK(plain_request_case(&b, 6u, 5u) == 0);

    /* one X (static) descriptor: two words */
    CHECK(expected_frame(1u << 0, 0, 0, 0) == 4);
    CHECK(plain_request_case(&b, 6u | (1u << 16), 7u) == 0);
    /* one A (send) descriptor: three words, frame moves to 8.  The packed
       descriptor_counts groups are X@0, A@4, B@8, W@12; in w0 they sit at bits
       16/20/24/28 respectively. */
    CHECK(expected_frame(1u << 4, 0, 0, 0) == 8);
    CHECK(plain_request_case(&b, 6u | (1u << 20), 7u) == 0);
    /* one B (receive) and one W (exchange) descriptor: three words each */
    CHECK(expected_frame(1u << 8, 0, 0, 0) == 8);
    CHECK(plain_request_case(&b, 6u | (1u << 24), 7u) == 0);
    CHECK(expected_frame(1u << 12, 0, 0, 0) == 8);
    CHECK(plain_request_case(&b, 6u | (1u << 28), 7u) == 0);
    /* mixed: one X and one A -> 2 + 2 + 3 = 7 -> frame 8 */
    CHECK(expected_frame((1u << 0) | (1u << 4), 0, 0, 0) == 8);
    CHECK(plain_request_case(&b, 6u | (1u << 16) | (1u << 20), 7u) == 0);

    /* special header, no process id: the header block is 3 words, frame stays 4 */
    CHECK(expected_frame(0, 1, 0, 0) == 4);
    Message m;
    build_request(&b, 6u, 0x80000000u, 0u, 0, 0u, 9u);
    require_parsed(&b, &m, __LINE__);
    CHECK(m.domain == 0);
    CHECK(m.frame == 4 && m.magic == 4 && m.command == 9);

    /* special header with a process id: two more words, frame 8 */
    build_request(&b, 6u, 0x80000000u, 1u, 0, 0u, 9u);
    require_parsed(&b, &m, __LINE__);
    CHECK(m.frame == expected_frame(0, 1, 1, 1)); /* == 8 */
    CHECK(m.magic == m.frame && m.command == 9);

    /* special header, one copy and one move handle, then a descriptor: the
       block is 3 + 2(pid) + 1 + 1 + 2(X) = 9 -> frame 12 */
    build_request(&b, 6u | (1u << 16), 0x80000000u, 1u | (1u << 1) | (1u << 5), 0, 0u, 11u);
    require_parsed(&b, &m, __LINE__);
    CHECK(m.frame == expected_frame(1u, 1, 1, 1u | (1u << 1) | (1u << 5))); /* == 12 */
    CHECK(m.magic == m.frame && m.command == 11);

    /* ---- domain SendMessage: cmd 1, data_size 16, magic at frame + 4 ---- */

    const size_t dframe = build_request(&b, 6u, 0u, 0u, 1, 42u, 13u);
    CHECK(b.w[dframe] == 0x00100001u); /* cmd 1, no objects, 16 data bytes */
    require_parsed(&b, &m, __LINE__);
    CHECK(m.domain == 1);
    CHECK(m.domain_command == 1);
    CHECK(m.domain_object == 42u);
    CHECK(m.frame == dframe);
    CHECK(m.magic == dframe + 4);
    CHECK(m.command == 13u);

    /* a domain message behind a special header and a process id: frame 8 */
    const size_t dframe2 = build_request(&b, 6u, 0x80000000u, 1u, 1, 7u, 13u);
    CHECK(b.w[dframe2] == 0x00100001u);
    require_parsed(&b, &m, __LINE__);
    CHECK(m.domain == 1 && m.domain_command == 1 && m.domain_object == 7u);
    CHECK(m.frame == dframe2 && m.magic == dframe2 + 4);

    /* ---- malformed shapes: each must be refused ---- */

    /* a descriptor count that pushes the header block past the message */
    buffer_reset(&b);
    b.w[0] = 6u | (0xffffu << 16); /* 15 X + 15 A + 15 B + 15 W descriptors */
    b.w[1] = 8u;
    b.w[8] = CMIF_IN;
    CHECK(message_parse(&m, (uint64_t)(uintptr_t)b.w) != 0);

    /* a raw count that runs past the message */
    buffer_reset(&b);
    b.w[0] = 6u;
    b.w[1] = 0x3ffu; /* raw_end far beyond the buffer */
    b.w[4] = CMIF_IN;
    CHECK(message_parse(&m, (uint64_t)(uintptr_t)b.w) != 0);

    /* a raw count too short to reach the frame, so the payload is outside it */
    buffer_reset(&b);
    b.w[0] = 6u;
    b.w[1] = 1u; /* one word of raw data: frame 4 lies outside it */
    b.w[4] = DOMAIN_HEADER(1, 0, 16);
    b.w[5] = 1u;
    b.w[8] = CMIF_IN;
    CHECK(message_parse(&m, (uint64_t)(uintptr_t)b.w) != 0);

    /* SFCI only outside the declared raw data: no full buffer scan may find it */
    buffer_reset(&b);
    b.w[0] = 6u;
    b.w[1] = 4u; /* raw_end 6; the magic below at word 18 is not declared */
    b.w[18] = CMIF_IN;
    b.w[19] = 1u;
    b.w[20] = 5u;
    CHECK(message_parse(&m, (uint64_t)(uintptr_t)b.w) != 0);

    /* SFCI in the header padding between the handle slots and the frame */
    buffer_reset(&b);
    b.w[0] = 6u;
    b.w[1] = 0x80000000u | 4u; /* special header, raw_end 7, frame 4 */
    b.w[3] = CMIF_IN;          /* padding, not the frame */
    b.w[18] = CMIF_IN;
    CHECK(message_parse(&m, (uint64_t)(uintptr_t)b.w) != 0);

    /* SFCI inside a buffer descriptor, not at the frame */
    buffer_reset(&b);
    b.w[0] = 6u | (1u << 16); /* one X descriptor occupies words 2 and 3 */
    b.w[1] = 4u;
    b.w[2] = CMIF_IN;         /* descriptor data */
    b.w[3] = 1u;
    CHECK(message_parse(&m, (uint64_t)(uintptr_t)b.w) != 0);

    /* a domain header that declares command 1 but zero data bytes */
    buffer_reset(&b);
    b.w[0] = 6u;
    b.w[1] = 8u;
    b.w[4] = DOMAIN_HEADER(1, 0, 0);
    b.w[5] = 1u;
    b.w[8] = CMIF_IN;
    CHECK(message_parse(&m, (uint64_t)(uintptr_t)b.w) != 0);

    /* a domain header whose declared data size overruns the raw data */
    buffer_reset(&b);
    b.w[0] = 6u;
    b.w[1] = 8u;
    b.w[4] = DOMAIN_HEADER(1, 0, 0x1000u);
    b.w[5] = 1u;
    b.w[8] = CMIF_IN;
    CHECK(message_parse(&m, (uint64_t)(uintptr_t)b.w) != 0);

    /* A frame at word 52 fits the CMIF header and five inspected argument words.
       Descriptor count 0x006f is
       15 X + 6 A descriptors -> index 50 -> frame 52. */
    build_request(&b, 6u | (0x006fu << 16), 0u, 0u, 0, 0u, 5u);
    CHECK(expected_frame(0x006fu, 0, 0, 0) == 52);
    require_parsed(&b, &m, __LINE__);
    CHECK(m.frame == 52 && m.magic == 52 && m.command == 5);

    /* One frame further (frame 56, magic 56) leaves fewer argument words than the
       handlers read, so the walker refuses instead of reading past the buffer:
       3 X + 15 A descriptors -> index 53 -> frame 56. */
    build_request(&b, 6u | (0x00f3u << 16), 0u, 0u, 0, 0u, 5u);
    CHECK(expected_frame(0x00f3u, 0, 0, 0) == 56);
    CHECK(b.w[56] == CMIF_IN);
    CHECK(message_parse(&m, (uint64_t)(uintptr_t)b.w) != 0);

    /* ---- dispatch: only a genuine bare HIPC close is accepted ---- */

    uint32_t session = d3_handle_alloc(D3_OBJ_SESSION, "appletOE", (uint64_t)PORT_UNKNOWN);
    CHECK(session != 0);

    /* A type 6 request that declares no payload at all must fail even when a
       stale SFCI sits behind it: it is not a bare HIPC close (w0 == 2). */
    buffer_reset(&b);
    b.w[0] = 6u;
    b.w[1] = 0u;
    b.w[8] = CMIF_IN; /* stale reply bytes */
    d3_saved saved = {0};
    saved.x[0] = session; /* SendSyncRequest carries the handle in x0 */
    d3_svc_send_sync_request(&saved, (uint64_t)(uintptr_t)b.w);
    CHECK(saved.x[0] != 0);

    /* The genuine bare HIPC close (w0 == 2, w1 == 0) is still answered. */
    buffer_reset(&b);
    b.w[0] = 2u;
    b.w[1] = 0u;
    d3_saved saved_close = {0};
    saved_close.x[0] = session;
    d3_svc_send_sync_request(&saved_close, (uint64_t)(uintptr_t)b.w);
    CHECK(saved_close.x[0] == 0);

    puts("PASS: the HIPC walker counts X/A/B/W descriptors, places the CMIF frame "
         "on the 16 byte boundary, recognizes a capture with one receive "
         "descriptor as a plain request (domain 0, frame 8, magic 8, cmd 5), "
         "validates the domain data size against the raw data, never scans for "
         "SFCI outside the declared frame, and accepts only a genuine bare HIPC "
         "close");
    return 0;
}
