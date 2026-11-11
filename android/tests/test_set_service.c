/* Android-native regression test: the set service language commands.

   The boot path opens sm:GetService("set") and immediately calls
   GetAvailableLanguageCodes2 (command 5 on HOS >= 4.0.0), whose output is a
   LanguageCode[] written into a guest receive buffer carried by a three word
   HIPC map (B) descriptor.  The host must decode that descriptor from its own
   words, refuse a short, badly moded or unwritable one with a Horizon result
   (never a host fault), and fill the buffer with the 18
   nn::settings::Language codes while reporting the same count.  This drives
   the real SendSyncRequestWithUserBuffer path, so it includes the service
   layer as one translation unit like the other tests. */
#include "../host/d3_service.c"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

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

#define REQUIRE(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "FATAL line %d: %s\n", __LINE__, #condition); \
        abort(); \
    } \
} while (0)

/* Descriptor word counts live in w0 bits 16..31, one nibble each: X (static) at
   0, A (send) at 4, B (receive) at 8, W (exchange) at 12. */
#define ONE_RECEIVE (1u << 24)
#define ONE_SEND    (1u << 20)
#define ONE_EXCHANGE (1u << 28)

/* The same 16 byte aligned HIPC TLS buffer the guest posts requests in. */
typedef struct { uint32_t w[MESSAGE_WORDS] __attribute__((aligned(16))); } Buffer;

/* The guest receive buffer lives in host address space in this fixture; the
   descriptor address must be a real pointer the self write can reach. */
#define BLANK_WORDS 0x40
static uint32_t g_blank[BLANK_WORDS] __attribute__((aligned(16)));
static uint32_t g_session;

/* The two sentinel words just past the 36 the 18 codes occupy, to prove the
   self write stays inside the 144 bytes the caller declared. */
#define CANARY_LO 0xdeadbeefu
#define CANARY_HI 0xcafebabeu

static void arm_canaries(void) {
    memset(g_blank, 0, sizeof g_blank);
    g_blank[36] = CANARY_LO;
    g_blank[37] = CANARY_HI;
}

/* The real APK hands back an output address that is only 4 byte aligned (it
   ended 0x916c) with a larger 0x200 declared size, so the fixture needs a byte
   buffer whose receive address lands on 4 mod 8.  The 18 codes occupy 144 bytes
   from that address; a canary word sits right after them and one before. */
static uint8_t g_unaligned[0x220] __attribute__((aligned(16)));

static void arm_unaligned(void) {
    memset(g_unaligned, 0, sizeof g_unaligned);
    const uint32_t before = CANARY_LO, after = CANARY_HI;
    memcpy(&g_unaligned[0], &before, sizeof before);          /* before the 144 bytes */
    memcpy(&g_unaligned[4u + 144u], &after, sizeof after);    /* right past them */
}

/* Read a u64 out of a guest buffer without assuming it is 8 byte aligned: a
   plain uint64_t* dereference of the APK's 0x916c output address is undefined. */
static uint64_t load_u64(const void *p) {
    uint64_t value;
    memcpy(&value, p, sizeof value);
    return value;
}

/* Read the two 4 byte canaries arm_unaligned planted (also via memcpy). */
static uint32_t load_u32(const void *p) {
    uint32_t value;
    memcpy(&value, p, sizeof value);
    return value;
}

/* Pack a LanguageCode string the way nn::settings::LanguageCode stores it: the
   little endian bytes of the NUL terminated text in a u64. */
static uint64_t code_of(const char *text) {
    uint64_t code = 0;
    for (size_t i = 0; i < 8 && text[i] != 0; i++)
        code |= (uint64_t)(uint8_t)text[i] << (8 * i);
    return code;
}

/* Encode one three word map (receive) descriptor, the inverse of the decoder
   under test: word0 = the low 32 size bits with the size's high 4 bits in word2
   bits 24..27; word1 = the low 32 address bits with the address's high 22 bits
   in word2 bits 2..23 and its middle 4 bits in word2 bits 28..31.  Masking only
   a few low bits here used to let a high size or address round trip wrong. */
static void encode_receive(uint32_t *word, uint64_t size, uint64_t address) {
    word[0] = (uint32_t)size;
    word[1] = (uint32_t)address;
    word[2] = (uint32_t)(((size >> 32) & 0xfu) << 24) |
              (uint32_t)(((address >> 36) & 0x3fffffu) << 2) |
              (uint32_t)(((address >> 32) & 0xfu) << 28);
}

/* Build a request with the given descriptor word counts and one three word map
   descriptor left for the caller to place at words 2..4, the CMIF payload at
   word 8 (a descriptor count pushes the header block to a 16 byte frame there)
   and arg0 at word 12.  The boot capture used ONE_RECEIVE and command 5. */
static void build_request(Buffer *b, uint32_t counts, uint32_t command, uint32_t arg0) {
    memset(b, 0, sizeof *b);
    b->w[0] = 6u | counts;
    b->w[1] = 8u; /* raw data: header + descriptor + pad + CMIF payload */
    b->w[8] = CMIF_IN;
    b->w[9] = 1u;
    b->w[10] = command;
    b->w[11] = 0u;
    b->w[12] = arg0;
}

/* Build a plain request: no buffer descriptors, so the header block is two
   words and the CMIF payload starts at word 4.  The scalar commands (0, 2, 3,
   4, 6) must answer with no descriptor at all; raw_words is the raw data length
   and arg0 lands at word 8 (magic + 4). */
static void build_plain(Buffer *b, uint32_t command, size_t raw_words, uint32_t arg0) {
    memset(b, 0, sizeof *b);
    b->w[0] = 6u;
    b->w[1] = (uint32_t)raw_words;
    b->w[4] = CMIF_IN;
    b->w[5] = 1u;
    b->w[6] = command;
    b->w[7] = 0u;
    b->w[8] = arg0;
}

typedef struct { uint32_t result; uint32_t out[2]; } Reply;

/* Where a reply's frame begins: the two header words, then the optional special
   header, rounded up to 16 bytes -- the same walk reply_prepare does.  A plain
   service reply (no move handles) has no special header, so frame == 4. */
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

/* Send one already built request through the real user-buffer dispatch and
   unpack the reply: CMIF magic at the frame, result two words later, the first
   out arguments at frame + 4 / + 5.  An infra fault aborts, so it propagates. */
static uint32_t send_words(uint32_t *words, Reply *r) {
    d3_saved saved = {0};
    saved.x[0] = (uint64_t)(uintptr_t)words;
    saved.x[2] = g_session;
    d3_svc_send_sync_request_user(&saved);
    REQUIRE(saved.x[0] == 0);
    const size_t frame = reply_frame(words);
    REQUIRE(words[frame] == CMIF_OUT);
    if (r != NULL) {
        r->result = words[frame + 2];
        r->out[0] = words[frame + 4];
        r->out[1] = words[frame + 5];
    }
    return words[frame + 2];
}

/* Send a request carrying one map descriptor at words 2..4. */
static uint32_t set_send(const uint32_t *descriptor, uint32_t counts, uint32_t command,
                         uint32_t arg0, Buffer *b, Reply *r) {
    build_request(b, counts, command, arg0);
    b->w[2] = descriptor[0];
    b->w[3] = descriptor[1];
    b->w[4] = descriptor[2];
    return send_words(b->w, r);
}

/* Send a descriptorless scalar request. */
static uint32_t plain_send(Buffer *b, uint32_t command, size_t raw_words, uint32_t arg0, Reply *r) {
    build_plain(b, command, raw_words, arg0);
    return send_words(b->w, r);
}

int main(void) {
    /* Keep every slog inside the compiler's reach from touching /sdcard. */
    g_log_tried = 1;
    g_log = -1;

    Buffer b;
    Reply r;
    uint32_t descriptor[3];

    /* ---- the descriptor codec, first without dispatching anything ---- */

    /* the low word and low address the self write can reach */
    encode_receive(descriptor, sizeof g_blank, (uint64_t)(uintptr_t)g_blank);
    CHECK(map_descriptor_size(descriptor) == sizeof g_blank);
    CHECK(map_descriptor_address(descriptor) == (uint64_t)(uintptr_t)g_blank);

    /* a high size (word2 bits 24..27) and a high address (word2 bits 2..23 and
       28..31) must round trip; the address is only decoded, never dereferenced */
    const uint64_t hi_size = ((uint64_t)0xfu << 32) | 0x144u;
    const uint64_t hi_addr = ((uint64_t)0x123u << 36) | ((uint64_t)0x5u << 32) | 0x12345000u;
    encode_receive(descriptor, hi_size, hi_addr);
    CHECK(map_descriptor_size(descriptor) == hi_size);
    CHECK(map_descriptor_address(descriptor) == hi_addr);

    g_session = d3_handle_alloc(D3_OBJ_SESSION, "set", (uint64_t)PORT_SET);
    CHECK(g_session != 0);
    CHECK(d3_handle_arg(g_session) == PORT_SET);

    /* ---- cmd5 GetAvailableLanguageCodes2: the real boot path ---- */

    /* exactly 18 * 8 = 144 bytes is enough and is filled, canaries intact */
    uint32_t exact[3];
    encode_receive(exact, 18u * sizeof(uint64_t), (uint64_t)(uintptr_t)g_blank);
    arm_canaries();
    CHECK(set_send(exact, ONE_RECEIVE, 5u, 0u, &b, &r) == 0);
    CHECK(r.result == 0);
    CHECK(r.out[0] == 18u); /* count matches the list length */
    const uint64_t *codes = (const uint64_t *)g_blank;
    CHECK(codes[0] == code_of("ja"));    /* index 0 = SetLanguage_JA */
    CHECK(codes[1] == code_of("en-US")); /* index 1 = the system language */
    CHECK(codes[17] == code_of("pt-BR"));
    CHECK(g_blank[36] == CANARY_LO && g_blank[37] == CANARY_HI);

    /* the real APK output address ended 0x916c: 4 byte aligned, not 8, with a
       larger 0x200 declared size.  The write is a byte copy, so only the size
       has to cover the 144 output bytes; the codes land unaligned and reads
       must go through memcpy, never an unaligned uint64_t*. */
    uint32_t apk_desc[3];
    encode_receive(apk_desc, 0x200u, (uint64_t)(uintptr_t)(g_unaligned + 4));
    arm_unaligned();
    CHECK(set_send(apk_desc, ONE_RECEIVE, 5u, 0u, &b, &r) == 0);
    CHECK(r.result == 0);
    CHECK(r.out[0] == 18u);
    CHECK(load_u64(g_unaligned + 4) == code_of("ja"));
    CHECK(load_u64(g_unaligned + 4 + 8) == code_of("en-US"));
    CHECK(load_u64(g_unaligned + 4 + 17 * 8) == code_of("pt-BR"));
    CHECK(load_u32(g_unaligned) == CANARY_LO);
    CHECK(load_u32(g_unaligned + 4 + 144) == CANARY_HI);

    /* a descriptor smaller than the 144 bytes the list needs (18, 24 and 143)
       is refused and the buffer is left alone: the wanted length is bytes, not
       the 18 element count, so 24 must fail too */
    const uint32_t short_sizes[] = { 18u, 24u, 143u };
    for (size_t i = 0; i < sizeof short_sizes / sizeof short_sizes[0]; i++) {
        uint32_t short_desc[3];
        encode_receive(short_desc, short_sizes[i], (uint64_t)(uintptr_t)g_blank);
        arm_canaries();
        CHECK(set_send(short_desc, ONE_RECEIVE, 5u, 0u, &b, &r) != 0);
        CHECK(r.result != 0);
        CHECK(g_blank[0] == 0u && g_blank[1] == 0u); /* nothing written */
        CHECK(g_blank[36] == CANARY_LO && g_blank[37] == CANARY_HI);
    }

    /* ---- writes that cannot land: a Horizon result, never a host fault ---- */

    /* a null address */
    uint32_t null_desc[3];
    encode_receive(null_desc, 18u * sizeof(uint64_t), 0u);
    CHECK(set_send(null_desc, ONE_RECEIVE, 5u, 0u, &b, &r) != 0);
    CHECK(r.result != 0);

    /* an unmapped / out of range address */
    uint32_t hole_desc[3];
    encode_receive(hole_desc, 18u * sizeof(uint64_t), 0x1000u);
    CHECK(set_send(hole_desc, ONE_RECEIVE, 5u, 0u, &b, &r) != 0);
    CHECK(r.result != 0);

    /* a PROT_NONE mapping */
    void *none = mmap(NULL, 0x1000, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    REQUIRE(none != MAP_FAILED);
    uint32_t none_desc[3];
    encode_receive(none_desc, 18u * sizeof(uint64_t), (uint64_t)(uintptr_t)none);
    CHECK(set_send(none_desc, ONE_RECEIVE, 5u, 0u, &b, &r) != 0);
    CHECK(r.result != 0);
    REQUIRE(munmap(none, 0x1000) == 0);

    /* a read only mapping */
    void *ro = mmap(NULL, 0x1000, PROT_READ, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    REQUIRE(ro != MAP_FAILED);
    uint32_t ro_desc[3];
    encode_receive(ro_desc, 18u * sizeof(uint64_t), (uint64_t)(uintptr_t)ro);
    CHECK(set_send(ro_desc, ONE_RECEIVE, 5u, 0u, &b, &r) != 0);
    CHECK(r.result != 0);
    REQUIRE(munmap(ro, 0x1000) == 0);

    /* a high bit of a real low address must stay in the decoded address, not be
       truncated back: flip a bit well inside the address's high field but past
       any user virtual address, so the write misses and the low buffer keeps
       its canaries (the old decoder dropped everything above word2 bit 4) */
    uint32_t hi_desc[3];
    encode_receive(hi_desc, 18u * sizeof(uint64_t),
                   (uint64_t)(uintptr_t)g_blank ^ ((uint64_t)1u << 55));
    arm_canaries();
    CHECK(set_send(hi_desc, ONE_RECEIVE, 5u, 0u, &b, &r) != 0);
    CHECK(r.result != 0);
    CHECK(g_blank[0] == 0u);
    CHECK(g_blank[36] == CANARY_LO && g_blank[37] == CANARY_HI);

    /* ---- a descriptor that is not the expected receive buffer ---- */

    /* mode 2 (the low two bits of word2) is not a valid map mode */
    uint32_t mode_desc[3];
    encode_receive(mode_desc, 18u * sizeof(uint64_t), (uint64_t)(uintptr_t)g_blank);
    mode_desc[2] |= 2u;
    CHECK(set_send(mode_desc, ONE_RECEIVE, 5u, 0u, &b, &r) != 0);
    CHECK(r.result != 0);

    /* a send only (A) or exchange only (W) descriptor must not be taken as the
       receive buffer */
    CHECK(set_send(exact, ONE_SEND, 5u, 0u, &b, &r) != 0);
    CHECK(r.result != 0);
    CHECK(set_send(exact, ONE_EXCHANGE, 5u, 0u, &b, &r) != 0);
    CHECK(r.result != 0);

    /* a request with no descriptor at all is refused */
    CHECK(plain_send(&b, 5u, 8u, 0u, &r) != 0);
    CHECK(r.result != 0);

    /* ---- cmd1 (legacy pointer Out) is not implemented: it stays a Horizon
       error, not a map write dressed up as success ---- */
    arm_canaries();
    CHECK(set_send(exact, ONE_RECEIVE, 1u, 0u, &b, &r) != 0);
    CHECK(r.result != 0);

    /* ---- descriptorless scalar commands 0, 2, 3, 4, 6 ---- */

    /* cmd0 GetLanguageCode -> the system en-US */
    CHECK(plain_send(&b, 0u, 8u, 0u, &r) == 0);
    CHECK(((uint64_t)r.out[1] << 32 | r.out[0]) == code_of("en-US"));

    /* cmd3 / cmd6 GetAvailableLanguageCodeCount(2) -> 18 */
    CHECK(plain_send(&b, 3u, 8u, 0u, &r) == 0);
    CHECK(r.out[0] == 18u);
    CHECK(plain_send(&b, 6u, 8u, 0u, &r) == 0);
    CHECK(r.out[0] == 18u);

    /* cmd4 GetRegionCode -> 1 (USA, matching en-US) */
    CHECK(plain_send(&b, 4u, 8u, 0u, &r) == 0);
    CHECK(r.out[0] == 1u);

    /* cmd2 MakeLanguageCode: the whole 32 bit enum word is validated (raw_words
       9 carries the enum as an s32), so 0x100 and 0xffffffff fail just like 18
       and 0x40 instead of passing through a masked low byte */
    CHECK(plain_send(&b, 2u, 9u, 1u, &r) == 0); /* AmericanEnglish */
    CHECK(((uint64_t)r.out[1] << 32 | r.out[0]) == code_of("en-US"));
    CHECK(plain_send(&b, 2u, 9u, 17u, &r) == 0); /* BrazilianPortuguese */
    CHECK(((uint64_t)r.out[1] << 32 | r.out[0]) == code_of("pt-BR"));
    const uint32_t bad_languages[] = { 0x100u, 0xffffffffu, 18u, 0x40u };
    for (size_t i = 0; i < sizeof bad_languages / sizeof bad_languages[0]; i++) {
        CHECK(plain_send(&b, 2u, 9u, bad_languages[i], &r) != 0);
        CHECK(r.result != 0);
    }

    /* ---- an unknown set command stays an error ---- */
    CHECK(set_send(exact, ONE_RECEIVE, 7u, 0u, &b, &r) != 0);
    CHECK(r.result != 0);

    puts("PASS: set decodes the three word receive descriptor with the full size "
         "and address fields, writes the 18 LanguageCodes into the guest buffer "
         "(including a 4 byte aligned 0x200 output like the APK's) with en-US "
         "readable, reports a matching count, answers commands 0..6 from scalar "
         "arguments and refuses a short, unwritable, badly moded, send only, "
         "exchange only, missing, legacy or unknown request without a host fault");
    return 0;
}
