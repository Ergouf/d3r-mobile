// d3_service.h - IPC service call handlers
#ifndef D3_SERVICE_H
#define D3_SERVICE_H

#include <stdint.h>
#include "guest_layout.h"

// SVC numbers
#define SVC_SEND_SYNC_REQUEST           0x21
#define SVC_SEND_SYNC_REQUEST_WITH_USER 0x22

// CMIF command IDs
#define CMIF_CMD_SEND_REQUEST  0  // Regular IPC call
#define CMIF_CMD_REQUEST       1  // Domain IPC
#define CMIF_CMD_CLOSE         2  // Domain close
#define CMIF_CMD_ON_RESPONSE   3  // Response (not sent)

// Well-known service handles
#define HANDLE_SM              0x0000  // Service Manager
#define HANDLE_LM              0x1001  // Logging Manager
#define HANDLE_LOGGER          0x1002  // Logger object

// Service Manager (sm) commands
#define SM_CMD_INITIALIZE      0
#define SM_CMD_GET_SERVICE     1

// Logging Manager (lm) commands
#define LM_CMD_OPEN_LOGGER     0
#define LM_CMD_LOGGER_LOG      0    // Logger object command

// Shared message buffer structure (simplified)
typedef struct {
    uint32_t magic;        // 0x4349464D ('CMIF')
    uint32_t version;      // 0
    uint32_t reserved1;
    uint32_t reserved2;
} cmif_header;

// SVC handler functions
void d3_svc_send_sync_request(d3_saved *saved);
void d3_svc_send_sync_request_with_user(d3_saved *saved);

// Core IPC functions
void send_sync(d3_saved *saved, uint64_t buffer, uint32_t handle, const char *name);
int message_parse(cmif_header *msg, uint32_t size);
void message_build_response(cmif_header *msg, int result);

// Service handlers
int handle_sm_command(uint32_t cmd, uint32_t request_id, const void *input);
int handle_lm_command(uint32_t cmd, uint32_t request_id, const void *input);
int handle_logger_command(uint32_t cmd, uint32_t request_id, const void *input);

#endif // D3_SERVICE_H
