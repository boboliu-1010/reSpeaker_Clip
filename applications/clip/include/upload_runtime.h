#ifndef CLIP_UPLOAD_H
#define CLIP_UPLOAD_H
#include <stdbool.h>
#include <stdint.h>
#include <zephyr/kernel.h>
#include "clip_event.h"
int upload_runtime_register(void);
#ifdef CONFIG_BOA_USER_BINDING
/* Record an immutable origin before audio is created; never relabel old files. */
int upload_runtime_recording_origin(const char *session_id);
/* Explicit FACTORY only: persistently clear provisioning before SD reset. */
int upload_runtime_factory_reset(void);
#endif
bool upload_runtime_active(void);
/* Whole job's completed-file percentage, or -1 when no upload batch is active.
 * Read-only; never touches storage/network or wakes the display. */
int upload_runtime_display_percent(void);
bool upload_runtime_record_pending(void);
int upload_runtime_set_time(int64_t timestamp);
int upload_runtime_record_error(void);
void upload_runtime_record_complete(enum clip_event_result result);
int upload_runtime_command_begin(const char *name, uint8_t type);
bool upload_runtime_event(enum clip_event event, struct clip_event_result_info *result,
                     bool device_idle);
int wifi_station_connect(const char *ssid, const char *password, atomic_t *cancel);
const char *wifi_station_last_step(void);
struct wifi_station_network {
    char ip[16], netmask[16], gateway[16];
};
void wifi_station_get_network(struct wifi_station_network *network);
#endif
