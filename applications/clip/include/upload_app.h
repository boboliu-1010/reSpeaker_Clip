/* Bounded BLE upload events; producers never send notifications or wait. */
#ifndef CLIP_UPLOAD_APP_H
#define CLIP_UPLOAD_APP_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

struct upload_app_status {
    const char *stage;
    uint32_t job, segment, sent, received, confirmed, size;
    int error, delete_error;
    bool delete_after_upload;
    bool active, automatic, enabled, paused, network_check;
    char session[15];
};
struct upload_app_network {
    const char *state;
    uint32_t job, checked_ms;
    int error, cleanup_error;
    char ip[16];
};
/* Snapshots are supplied by the uploader; no credentials are exposed. */
void upload_runtime_app_status(struct upload_app_status *out);
void upload_runtime_app_network(struct upload_app_network *out);
int upload_app_format_status(const struct upload_app_status *s, const char *type,
                             uint32_t seq, uint32_t lost, char *out, size_t size);
int upload_app_format_network(const struct upload_app_network *s, bool event,
                              uint32_t seq, uint32_t lost, char *out, size_t size);
void upload_app_publish(const char *type);
void upload_app_publish_result(const char *type, const struct upload_app_status *status);
void upload_app_publish_network(const struct upload_app_network *status);
/* Called only by the AT thread, outside the upload control mutex. */
void upload_app_poll(void);
void upload_app_resync(void);
#endif
