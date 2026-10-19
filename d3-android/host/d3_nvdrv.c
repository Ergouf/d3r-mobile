#define _GNU_SOURCE
#include "d3_nvdrv.h"

#include <pthread.h>
#include <string.h>
#include <sys/uio.h>
#include <unistd.h>
#ifdef D3_WITH_GPU
#include "../gpu/host/gpu_bridge.h"
#endif

enum { NV_SUCCESS, NV_NOT_IMPLEMENTED, NV_NOT_SUPPORTED, NV_NOT_INITIALIZED,
       NV_BAD_PARAMETER, NV_TIMEOUT, NV_NO_MEMORY, NV_READ_ONLY, NV_INVALID_STATE,
       NV_INVALID_ADDRESS, NV_INVALID_SIZE, NV_BAD_VALUE };
enum { NV_CTRL_GPU = 1, NV_MAP = 2, NV_AS_GPU = 3, NV_CHANNEL = 4 };

typedef struct {
    uint32_t session;
    uint32_t kind;
    uint32_t initialized;
    uint32_t big_page;
    uint64_t start;
    uint64_t split;
    uint64_t end;
    uint32_t gpu_space;
    uint32_t gpu_channel;
    uint32_t bound_space;
    uint32_t nvmap_fd;
    uint32_t syncpoint;
    uint32_t fence_value;
    uint32_t timeout;
    uint32_t priority;
    uint32_t timeslice;
    uint32_t contexts;
    uint64_t user_data;
    uint32_t notifier_handle;
    uint64_t notifier_offset;
    uint64_t notifier_size;
    uint64_t zcull_address;
    uint32_t zcull_mode;
} NvDescriptor;

typedef struct {
    uint32_t id;
    uint32_t size;
    uint32_t alignment;
    uint32_t kind;
    uint32_t references;
    uint64_t address;
} NvMapping;

static NvDescriptor g_descriptors[64];
static NvMapping g_mappings[1024];
static uint32_t g_mapping_id;
static uint32_t g_channel_syncpoint;
static pthread_mutex_t g_nv_mutex = PTHREAD_MUTEX_INITIALIZER;

typedef struct {
    NvDescriptor *owner;
    uint64_t address;
    uint64_t size;
    uint32_t page_size;
} NvReservation;

static NvReservation g_reservations[256];

typedef struct {
    NvDescriptor *owner;
    uint64_t address;
    uint64_t size;
    NvMapping *mapping;
} NvGpuMapping;

static NvGpuMapping g_gpu_mappings[256];

uint32_t d3_nv_open(uint32_t session, const char *path, uint32_t *descriptor) {
    uint32_t kind;
    *descriptor = UINT32_MAX;
    if (strcmp(path, "/dev/nvhost-ctrl-gpu") == 0)
        kind = NV_CTRL_GPU;
    else if (strcmp(path, "/dev/nvmap") == 0)
        kind = NV_MAP;
    else if (strcmp(path, "/dev/nvhost-as-gpu") == 0)
        kind = NV_AS_GPU;
    else if (strcmp(path, "/dev/nvhost-gpu") == 0)
        kind = NV_CHANNEL;
    else if (strcmp(path, "/dev/nvhost-prof-gpu") == 0)
        return NV_NOT_SUPPORTED;
    else
        return 0x30011u;
    pthread_mutex_lock(&g_nv_mutex);
    for (uint32_t index = 0; index < 64; index++) {
        if (!g_descriptors[index].kind) {
            g_descriptors[index] = (NvDescriptor){.session = session, .kind = kind};
            if (kind == NV_CHANNEL) {
                if (g_channel_syncpoint >= 191) {
                    g_descriptors[index] = (NvDescriptor){0};
                    pthread_mutex_unlock(&g_nv_mutex);
                    return NV_NO_MEMORY;
                }
                g_descriptors[index].syncpoint = ++g_channel_syncpoint;
#ifdef D3_WITH_GPU
                g_descriptors[index].gpu_channel = d3_gpu_nv_channel_create();
                if (!g_descriptors[index].gpu_channel) {
                    g_descriptors[index] = (NvDescriptor){0};
                    pthread_mutex_unlock(&g_nv_mutex);
                    return NV_NO_MEMORY;
                }
#endif
            }
            *descriptor = index + 1;
            pthread_mutex_unlock(&g_nv_mutex);
            return NV_SUCCESS;
        }
    }
    pthread_mutex_unlock(&g_nv_mutex);
    return NV_NO_MEMORY;
}

uint32_t d3_nv_close(uint32_t session, uint32_t descriptor) {
    pthread_mutex_lock(&g_nv_mutex);
    if (!descriptor || descriptor > 64 || !g_descriptors[descriptor - 1].kind ||
        g_descriptors[descriptor - 1].session != session) {
        pthread_mutex_unlock(&g_nv_mutex);
        return NV_BAD_VALUE;
    }
    if (g_descriptors[descriptor - 1].kind == NV_AS_GPU) {
        for (size_t index = 0; index < 64; index++) {
            if (g_descriptors[index].kind == NV_CHANNEL &&
                g_descriptors[index].bound_space == descriptor) {
                pthread_mutex_unlock(&g_nv_mutex);
                return NV_INVALID_STATE;
            }
        }
    }
    const uint32_t notifier_handle = g_descriptors[descriptor - 1].notifier_handle;
    for (size_t index = 0; index < 1024; index++) {
        if (notifier_handle && g_mappings[index].id == notifier_handle &&
            --g_mappings[index].references == 0)
            memset(&g_mappings[index], 0, sizeof g_mappings[index]);
    }
    for (size_t index = 0; index < 256; index++) {
        if (g_reservations[index].owner == &g_descriptors[descriptor - 1])
            memset(&g_reservations[index], 0, sizeof g_reservations[index]);
        if (g_gpu_mappings[index].owner == &g_descriptors[descriptor - 1])
            memset(&g_gpu_mappings[index], 0, sizeof g_gpu_mappings[index]);
    }
#ifdef D3_WITH_GPU
    if (g_descriptors[descriptor - 1].gpu_channel)
        d3_gpu_nv_channel_close(g_descriptors[descriptor - 1].gpu_channel);
    if (g_descriptors[descriptor - 1].gpu_space)
        d3_gpu_nv_as_close(g_descriptors[descriptor - 1].gpu_space);
#endif
    g_descriptors[descriptor - 1] = (NvDescriptor){0};
    pthread_mutex_unlock(&g_nv_mutex);
    return NV_SUCCESS;
}

static NvMapping *nv_mapping(uint32_t id) {
    for (size_t index = 0; index < 1024; index++) {
        if (id && g_mappings[index].id == id)
            return &g_mappings[index];
    }
    return NULL;
}

uint32_t d3_nv_buffer_pin(uint32_t id, uint64_t *address, uint64_t *size) {
    if (!address || !size)
        return NV_BAD_PARAMETER;
    pthread_mutex_lock(&g_nv_mutex);
    NvMapping *mapping = nv_mapping(id);
    const uint32_t result = mapping && mapping->address && mapping->references < UINT32_MAX ?
                            NV_SUCCESS : NV_BAD_VALUE;
    if (result == NV_SUCCESS) {
        mapping->references++;
        *address = mapping->address;
        *size = mapping->size;
    }
    pthread_mutex_unlock(&g_nv_mutex);
    return result;
}

void d3_nv_buffer_unpin(uint32_t id) {
    pthread_mutex_lock(&g_nv_mutex);
    NvMapping *mapping = nv_mapping(id);
    if (mapping && --mapping->references == 0)
        memset(mapping, 0, sizeof *mapping);
    pthread_mutex_unlock(&g_nv_mutex);
}

static uint32_t nvmap_ioctl(uint32_t command, uint32_t *parameters) {
    switch (command) {
    case 0xc0080101u: case 0xc0080103u: case 0xc0200104u: case 0xc0180105u:
    case 0xc00c0109u: case 0xc008010eu:
        break;
    default:
        return NV_NOT_IMPLEMENTED;
    }
    const uint32_t operation = command & 0xffu;
    if (operation == 1 && command == 0xc0080101u) {
        if (!parameters[0])
            return NV_BAD_VALUE;
        for (size_t index = 0; index < 1024; index++) {
            if (g_mappings[index].id)
                continue;
            const uint32_t id = ++g_mapping_id;
            g_mappings[index] = (NvMapping){.id = id, .size = parameters[0], .references = 1};
            parameters[1] = id;
            return NV_SUCCESS;
        }
        return NV_NO_MEMORY;
    }
    const uint32_t id = operation == 14 ? parameters[1] : parameters[0];
    NvMapping *mapping = nv_mapping(id);
    if (!mapping)
        return NV_BAD_VALUE;
    switch (command) {
    case 0xc0080103u:
        mapping->references++;
        parameters[1] = mapping->id;
        return NV_SUCCESS;
    case 0xc0200104u: {
        const uint32_t alignment = parameters[3] < 4096 ? 4096 : parameters[3];
        uint64_t address;
        memcpy(&address, &parameters[6], sizeof address);
        if ((alignment & (alignment - 1u)) || !address || (address & 4095u))
            return NV_BAD_VALUE;
        if (mapping->address)
            return NV_NO_MEMORY;
        mapping->alignment = alignment;
        mapping->kind = parameters[4] & 0xffu;
        mapping->address = address;
        parameters[3] = alignment;
        return NV_SUCCESS;
    }
    case 0xc0180105u:
        memcpy(&parameters[2], &mapping->address, sizeof mapping->address);
        parameters[4] = mapping->size;
        parameters[5] = 0;
        if (--mapping->references == 0)
            memset(mapping, 0, sizeof *mapping);
        return NV_SUCCESS;
    case 0xc00c0109u:
        switch (parameters[1]) {
        case 1: parameters[2] = mapping->size; break;
        case 2: parameters[2] = mapping->alignment; break;
        case 3: parameters[2] = (uint32_t)-22; break;
        case 4: parameters[2] = mapping->address ? 0x40000000u : 0; break;
        case 5: parameters[2] = mapping->kind; break;
        case 6: parameters[2] = 0; break;
        default: return NV_BAD_VALUE;
        }
        return NV_SUCCESS;
    case 0xc008010eu:
        parameters[0] = mapping->id;
        return NV_SUCCESS;
    default:
        return NV_NOT_IMPLEMENTED;
    }
}

static uint32_t ctrl_gpu_ioctl(uint32_t command, uint32_t *parameters,
                                void *inline_output, size_t inline_size) {
    switch (command) {
    case 0xc0b04705u: {
        static const uint32_t characteristics[40] = {
            0x120, 0xb, 0xa1, 1, 0x40000, 0, 0, 0, 2, 0x20,
            0x20000, 0x20000, 0x1b, 0x30000, 1, 0x503, 0x503, 0x80, 0x28, 0,
            0x55, 0, 0x902d, 0xb197, 0xb1c0, 0xb06f, 0xa140, 0xb0b5, 1, 0,
            2, 1, 0, 1, 0x21d70, 0, 0x30326d67, 0x62, 0, 0
        };
        parameters[0] = 0xa0;
        parameters[1] = 0;
        memcpy(parameters + 4, characteristics, sizeof characteristics);
        if (inline_size) {
            if (inline_size < sizeof characteristics)
                return NV_INVALID_SIZE;
            memcpy(inline_output, characteristics, sizeof characteristics);
        }
        return NV_SUCCESS;
    }
    case 0xc0184706u:
        parameters[4] = 3;
        if (inline_size >= 4)
            memcpy(inline_output, parameters + 4, 4);
        return NV_SUCCESS;
    case 0x80044701u:
        parameters[0] = 1;
        return NV_SUCCESS;
    case 0x80084714u:
        parameters[0] = 7;
        parameters[1] = 1;
        return NV_SUCCESS;
    case 0x80284702u: {
        static const uint32_t zcull[10] = {0x20, 0x20, 0x400, 0x800, 0x20, 0x20,
                                          0xc0, 0x20, 0x40, 0x10};
        memcpy(parameters, zcull, sizeof zcull);
        return NV_SUCCESS;
    }
    default:
        return NV_NOT_IMPLEMENTED;
    }
}

static uint32_t as_gpu_ioctl(NvDescriptor *descriptor, uint32_t command, uint32_t *parameters,
                              void *inline_output, size_t inline_size) {
    if (command == 0x40284109u) {
        if (descriptor->initialized)
            return NV_INVALID_STATE;
        const uint32_t big_page = parameters[2] ? parameters[2] : 0x20000u;
        if (big_page != 0x10000u && big_page != 0x20000u)
            return NV_BAD_VALUE;
        uint64_t ranges[3];
        memcpy(ranges, parameters + 4, sizeof ranges);
        descriptor->start = ranges[0] ? ranges[0] : (uint64_t)big_page << 10u;
        descriptor->end = ranges[0] ? ranges[1] : UINT64_C(1) << 37u;
        descriptor->split = ranges[0] ? ranges[2] : UINT64_C(1) << 34u;
        if (descriptor->start >= descriptor->split || descriptor->split >= descriptor->end)
            return NV_BAD_VALUE;
        descriptor->big_page = big_page;
#ifdef D3_WITH_GPU
        descriptor->gpu_space = d3_gpu_nv_as_create(big_page);
        if (!descriptor->gpu_space)
            return NV_NO_MEMORY;
#endif
        descriptor->initialized = 1;
        return NV_SUCCESS;
    }
    if (!descriptor->initialized)
        return NV_BAD_VALUE;
    if (command == 0x40044101u) {
        const uint32_t channel_fd = parameters[0];
        if (!channel_fd || channel_fd > 64)
            return NV_BAD_VALUE;
        NvDescriptor *channel = &g_descriptors[channel_fd - 1];
        if (channel->kind != NV_CHANNEL || channel->session != descriptor->session)
            return NV_BAD_VALUE;
        if (channel->bound_space)
            return NV_INVALID_STATE;
#ifdef D3_WITH_GPU
        const uint32_t result = d3_gpu_nv_channel_bind(channel->gpu_channel, descriptor->gpu_space);
        if (result)
            return result;
        if (channel->initialized) {
            const uint32_t init_result = d3_gpu_nv_channel_init(channel->gpu_channel);
            if (init_result)
                return init_result;
        }
#endif
        channel->bound_space = (uint32_t)(descriptor - g_descriptors) + 1;
        return NV_SUCCESS;
    }
    if (command == 0xc0284106u) {
        NvMapping *mapping = nv_mapping(parameters[2]);
        uint64_t buffer_offset, mapping_size, address;
        memcpy(&buffer_offset, parameters + 4, 8);
        memcpy(&mapping_size, parameters + 6, 8);
        memcpy(&address, parameters + 8, 8);
        if (parameters[0] & 0x100u) {
            if (parameters[0] & ~0x105u)
                return NV_NOT_IMPLEMENTED;
            if (!mapping_size || (mapping_size & 4095u) || (buffer_offset & 4095u))
                return NV_BAD_VALUE;
            for (size_t index = 0; index < 256; index++) {
                const NvGpuMapping *existing = &g_gpu_mappings[index];
                if (existing->owner != descriptor || existing->address != address)
                    continue;
                if (buffer_offset > existing->size || mapping_size > existing->size - buffer_offset)
                    return NV_BAD_VALUE;
#ifdef D3_WITH_GPU
                const uint32_t kind = parameters[1] == UINT32_MAX ? existing->mapping->kind : parameters[1];
                return d3_gpu_nv_rekind(descriptor->gpu_space, address, buffer_offset, mapping_size, kind);
#else
                return NV_NOT_IMPLEMENTED;
#endif
            }
            return NV_BAD_VALUE;
        }
        if (!mapping || !mapping->address || buffer_offset > mapping->size)
            return NV_BAD_VALUE;
        if (!mapping_size)
            mapping_size = mapping->size - buffer_offset;
        if (!mapping_size || mapping_size > mapping->size - buffer_offset ||
            (mapping_size & 4095u) || (buffer_offset & 4095u))
            return NV_BAD_VALUE;
        if (parameters[0] & ~5u)
            return NV_NOT_IMPLEMENTED;
        if (!(parameters[0] & 1u)) {
            const uint32_t page_size = mapping->alignment >= descriptor->big_page ? descriptor->big_page : 4096;
            address = page_size == 4096 ? descriptor->start : descriptor->split;
            for (;;) {
                int overlap = 0;
                for (size_t index = 0; index < 256; index++) {
                    const NvGpuMapping *existing = &g_gpu_mappings[index];
                    if (existing->owner == descriptor && address < existing->address + existing->size &&
                        existing->address < address + mapping_size) {
                        address = (existing->address + existing->size + page_size - 1u) & ~(uint64_t)(page_size - 1u);
                        overlap = 1;
                        break;
                    }
                    const NvReservation *reservation = &g_reservations[index];
                    if (reservation->owner == descriptor && address < reservation->address + reservation->size &&
                        reservation->address < address + mapping_size) {
                        address = (reservation->address + reservation->size + page_size - 1u) & ~(uint64_t)(page_size - 1u);
                        overlap = 1;
                        break;
                    }
                }
                if (!overlap)
                    break;
            }
            const uint64_t end = page_size == 4096 ? descriptor->split : descriptor->end;
            if (address >= end || mapping_size > end - address)
                return NV_NO_MEMORY;
        }
        int reserved = 0;
        for (size_t index = 0; index < 256; index++) {
            const NvReservation *reservation = &g_reservations[index];
            if (reservation->owner == descriptor && address >= reservation->address &&
                address - reservation->address <= reservation->size &&
                mapping_size <= reservation->size - (address - reservation->address))
                reserved = 1;
            const NvGpuMapping *existing = &g_gpu_mappings[index];
            if (existing->owner == descriptor && address < existing->address + existing->size &&
                existing->address < address + mapping_size)
                return NV_BAD_VALUE;
        }
        if (!reserved && (parameters[0] & 1u))
            return NV_BAD_VALUE;
        for (size_t index = 0; index < 256; index++) {
            if (g_gpu_mappings[index].owner)
                continue;
#ifdef D3_WITH_GPU
            const uint32_t kind = parameters[1] == UINT32_MAX ? mapping->kind : parameters[1];
            const uint32_t result = d3_gpu_nv_map(descriptor->gpu_space, address,
                                                  mapping->address + buffer_offset, mapping_size, kind);
            if (result)
                return result;
            g_gpu_mappings[index] = (NvGpuMapping){descriptor, address, mapping_size, mapping};
            memcpy(parameters + 8, &address, 8);
            mapping->references++;
            return NV_SUCCESS;
#else
            return NV_NOT_IMPLEMENTED;
#endif
        }
        return NV_NO_MEMORY;
    }
    if (command == 0x40084105u || command == 0xc0084105u) {
        uint64_t address;
        memcpy(&address, parameters, 8);
        for (size_t index = 0; index < 256; index++) {
            NvGpuMapping *mapping = &g_gpu_mappings[index];
            if (mapping->owner != descriptor || mapping->address != address)
                continue;
#ifdef D3_WITH_GPU
            const uint32_t result = d3_gpu_nv_unmap(descriptor->gpu_space, address, mapping->size);
            if (result)
                return result;
#endif
            if (--mapping->mapping->references == 0)
                memset(mapping->mapping, 0, sizeof *mapping->mapping);
            memset(mapping, 0, sizeof *mapping);
            return NV_SUCCESS;
        }
        return NV_BAD_VALUE;
    }
    if (command == 0xc0184102u) {
        const uint32_t pages = parameters[0];
        const uint32_t page_size = parameters[1];
        const uint32_t flags = parameters[2];
        if (!pages || (page_size != 4096 && page_size != descriptor->big_page))
            return NV_BAD_VALUE;
        if (flags & ~1u)
            return NV_NOT_IMPLEMENTED;
        uint64_t address;
        memcpy(&address, parameters + 4, sizeof address);
        const uint64_t bytes = (uint64_t)pages * page_size;
        const uint64_t start = page_size == 4096 ? descriptor->start : descriptor->split;
        const uint64_t end = page_size == 4096 ? descriptor->split : descriptor->end;
        if (!(flags & 1u))
            address = start;
        for (;;) {
            if (address < start || address > end || bytes > end - address ||
                (address & (page_size - 1u)))
                return NV_BAD_VALUE;
            int overlap = 0;
            for (size_t index = 0; index < 256; index++) {
                const NvReservation *reservation = &g_reservations[index];
                if (reservation->owner == descriptor && address < reservation->address + reservation->size &&
                    reservation->address < address + bytes) {
                    if (flags & 1u)
                        return NV_BAD_VALUE;
                    address = reservation->address + reservation->size;
                    overlap = 1;
                    break;
                }
            }
            if (!overlap)
                break;
        }
        for (size_t index = 0; index < 256; index++) {
            if (g_reservations[index].owner)
                continue;
            g_reservations[index] = (NvReservation){descriptor, address, bytes, page_size};
            memcpy(parameters + 4, &address, sizeof address);
            return NV_SUCCESS;
        }
        return NV_NO_MEMORY;
    }
    if (command == 0x40104103u || command == 0xc0104103u) {
        uint64_t address;
        memcpy(&address, parameters, sizeof address);
        for (size_t index = 0; index < 256; index++) {
            NvReservation *reservation = &g_reservations[index];
            if (reservation->owner != descriptor || reservation->address != address)
                continue;
            if (reservation->size != (uint64_t)parameters[2] * parameters[3] ||
                reservation->page_size != parameters[3])
                return NV_BAD_VALUE;
            memset(reservation, 0, sizeof *reservation);
            return NV_SUCCESS;
        }
        return NV_BAD_VALUE;
    }
    if (command == 0xc0404108u) {
        uint64_t regions[6] = {descriptor->start, 4096,
                                (descriptor->split - descriptor->start) / 4096,
                                descriptor->split, descriptor->big_page,
                                (descriptor->end - descriptor->split) / descriptor->big_page};
        parameters[2] = sizeof regions;
        memcpy(parameters + 4, regions, sizeof regions);
        if (inline_size) {
            if (inline_size < sizeof regions)
                return NV_INVALID_SIZE;
            memcpy(inline_output, regions, sizeof regions);
        }
        return NV_SUCCESS;
    }
    return NV_NOT_IMPLEMENTED;
}

static uint32_t channel_ioctl(NvDescriptor *descriptor, uint32_t command, uint32_t *parameters) {
    switch (command) {
    case 0xc010480bu: {
        uint64_t address;
        memcpy(&address, parameters, 8);
        if (parameters[2] > 3)
            return NV_BAD_PARAMETER;
        if (address) {
            int mapped = 0;
            for (size_t index = 0; index < 256; index++) {
                const NvGpuMapping *mapping = &g_gpu_mappings[index];
                if (mapping->owner && descriptor->bound_space &&
                    mapping->owner == &g_descriptors[descriptor->bound_space - 1] &&
                    address >= mapping->address && address - mapping->address < mapping->size)
                    mapped = 1;
            }
            if (!mapped)
                return NV_INVALID_ADDRESS;
        }
        descriptor->zcull_address = address;
        descriptor->zcull_mode = parameters[2];
        return NV_SUCCESS;
    }
    case 0xc018480cu: {
        uint64_t offset, bytes;
        memcpy(&offset, parameters, 8);
        memcpy(&bytes, parameters + 2, 8);
        NvMapping *mapping = nv_mapping(parameters[4]);
        if (parameters[4]) {
            if (!mapping || !mapping->address || bytes < 16 || offset > mapping->size ||
                bytes > mapping->size - offset)
                return NV_BAD_VALUE;
            const uint64_t zero[2] = {0};
            struct iovec source = {(void *)zero, sizeof zero};
            struct iovec destination = {(void *)(uintptr_t)(mapping->address + offset), sizeof zero};
#ifdef D3_WITH_GPU
            d3_gpu_begin_cpu_write(mapping->address + offset, sizeof zero);
#endif
            const ssize_t wrote = process_vm_writev(getpid(), &source, 1, &destination, 1, 0);
#ifdef D3_WITH_GPU
            d3_gpu_end_cpu_write();
#endif
            if (wrote != sizeof zero)
                return NV_INVALID_ADDRESS;
            mapping->references++;
        }
        NvMapping *previous = nv_mapping(descriptor->notifier_handle);
        if (previous && --previous->references == 0)
            memset(previous, 0, sizeof *previous);
        descriptor->notifier_handle = parameters[4];
        descriptor->notifier_offset = offset;
        descriptor->notifier_size = bytes;
        return NV_SUCCESS;
    }
    case 0x40044801u: {
        const uint32_t nvmap = parameters[0];
        if (!nvmap || nvmap > 64 || g_descriptors[nvmap - 1].kind != NV_MAP ||
            g_descriptors[nvmap - 1].session != descriptor->session)
            return NV_BAD_VALUE;
        descriptor->nvmap_fd = nvmap;
        return NV_SUCCESS;
    }
    case 0x40044803u:
        descriptor->timeout = parameters[0];
        return NV_SUCCESS;
    case 0x4004480du:
        if (parameters[0] != 50 && parameters[0] != 100 && parameters[0] != 150)
            return NV_BAD_PARAMETER;
        descriptor->priority = parameters[0];
        return NV_SUCCESS;
    case 0x4004481du:
    case 0xc004481du:
        if (parameters[0] < 1000 || parameters[0] > 5000)
            return NV_BAD_PARAMETER;
        descriptor->timeslice = parameters[0];
        return NV_SUCCESS;
    case 0x40084714u:
        memcpy(&descriptor->user_data, parameters, 8);
        return NV_SUCCESS;
    case 0x80084715u:
        memcpy(parameters, &descriptor->user_data, 8);
        return NV_SUCCESS;
    case 0xc0080003u:
        parameters[1] = 0;
        return NV_SUCCESS;
    case 0xc0104809u: {
        const uint32_t classes[] = {0x902d, 0xb197, 0xb1c0, 0xa140, 0xb0b5, 0xb06f};
        if (parameters[1])
            return NV_BAD_PARAMETER;
        for (uint32_t index = 0; index < 6; index++) {
            if (classes[index] != parameters[0])
                continue;
            if (descriptor->contexts & (1u << index))
                return 13;
            descriptor->contexts |= 1u << index;
            return NV_SUCCESS;
        }
        return NV_BAD_PARAMETER;
    }
    case 0xc0204818u:
    case 0xc020481au:
        if (descriptor->initialized)
            return 13;
        if (!parameters[0])
            return NV_BAD_VALUE;
#ifdef D3_WITH_GPU
        if (descriptor->bound_space) {
            const uint32_t result = d3_gpu_nv_channel_init(descriptor->gpu_channel);
            if (result)
                return result;
        }
#endif
        descriptor->initialized = 1;
        parameters[3] = descriptor->syncpoint;
        parameters[4] = descriptor->fence_value;
        return NV_SUCCESS;
    default:
        return NV_NOT_IMPLEMENTED;
    }
}

uint32_t d3_nv_ioctl(uint32_t session, uint32_t descriptor, uint32_t command,
                     void *parameters, size_t size, void *inline_output, size_t inline_size) {
    if (size != ((command >> 16u) & 0x3fffu) || !parameters)
        return NV_INVALID_SIZE;
    pthread_mutex_lock(&g_nv_mutex);
    if (!descriptor || descriptor > 64 || !g_descriptors[descriptor - 1].kind ||
        g_descriptors[descriptor - 1].session != session) {
        pthread_mutex_unlock(&g_nv_mutex);
        return NV_BAD_VALUE;
    }
    uint32_t result = NV_NOT_IMPLEMENTED;
    const uint32_t kind = g_descriptors[descriptor - 1].kind;
    if (kind == NV_CTRL_GPU)
        result = ctrl_gpu_ioctl(command, parameters, inline_output, inline_size);
    else if (kind == NV_MAP && ((command >> 8u) & 0xffu) == 1)
        result = nvmap_ioctl(command, parameters);
    else if (kind == NV_AS_GPU)
        result = as_gpu_ioctl(&g_descriptors[descriptor - 1], command, parameters,
                              inline_output, inline_size);
    else if (kind == NV_CHANNEL)
        result = channel_ioctl(&g_descriptors[descriptor - 1], command, parameters);
    pthread_mutex_unlock(&g_nv_mutex);
    return result;
}

uint32_t d3_nv_submit(uint32_t session, uint32_t descriptor, uint32_t *parameters,
                      const uint64_t *entries, size_t size) {
    if (!parameters || !entries || !parameters[2] || parameters[2] > 4096 ||
        (uint64_t)parameters[2] * 8 > size)
        return NV_INVALID_SIZE;
    pthread_mutex_lock(&g_nv_mutex);
    uint32_t result = NV_BAD_VALUE;
    if (descriptor && descriptor <= 64) {
        NvDescriptor *channel = &g_descriptors[descriptor - 1];
        if (channel->kind == NV_CHANNEL && channel->session == session &&
            channel->initialized && channel->bound_space) {
            const uint32_t flags = parameters[3];
            if ((flags & ~0x117u) || ((flags & 1u) && (flags & 0x100u))) {
                result = NV_BAD_PARAMETER;
            } else {
#ifdef D3_WITH_GPU
                result = d3_gpu_nv_submit(channel->gpu_channel, entries, parameters[2], flags,
                                          parameters[4], parameters[5], channel->syncpoint);
#else
                result = NV_NOT_IMPLEMENTED;
#endif
                if (!result) {
                    channel->fence_value += ((flags & 2u) ? 2 : 0) + ((flags & 0x100u) ? parameters[5] : 0);
                    parameters[3] = 0;
                    parameters[4] = channel->syncpoint;
                    parameters[5] = channel->fence_value;
                }
            }
        }
    }
    pthread_mutex_unlock(&g_nv_mutex);
    return result;
}
