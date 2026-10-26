#ifndef CLIP_UPLOAD_H
#define CLIP_UPLOAD_H
#include <stdbool.h>
#include <stdint.h>
#include <zephyr/kernel.h>
#include "clip_event.h"
int upload_runtime_register(void);
bool upload_runtime_active(void);
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
