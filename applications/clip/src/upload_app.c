#include "upload_app.h"
#include "ble.h"
#include <zephyr/kernel.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

struct app_event {
    uint32_t seq;
    const char *type;
    bool network;
    union { struct upload_app_status upload; struct upload_app_network wifi; } value;
};
K_MSGQ_DEFINE(app_events, sizeof(struct app_event), 8, 4);
static atomic_t sequence, lost, resync = ATOMIC_INIT(1);
static bool subscribed, pending_valid, previous_valid;
static struct app_event pending;
static struct upload_app_status previous;
static int64_t last_poll, last_progress;

int upload_app_format_status(const struct upload_app_status *s, const char *type,
                             uint32_t seq, uint32_t dropped, char *out, size_t size)
{
    int n = type ? snprintf(out, size,
        "{\"event\":\"upload\",\"type\":\"%s\",\"seq\":%u,\"lost\":%u,", type, seq, dropped) :
        snprintf(out, size, "{\"ok\":true,\"data\":{");
    if (n < 0 || (size_t)n >= size) { return -ENOSPC; }
    int tail = snprintf(out+n, size-n,
        "\"kind\":\"%s\",\"job\":%u,\"session\":\"%s\",\"segment\":%u,\"stage\":\"%s\","
        "\"active\":%s,\"automatic\":%s,\"enabled\":%s,\"paused\":%s,"
        "\"sent\":%u,\"received\":%u,\"confirmed\":%u,\"size\":%u,\"last_error\":%d,"
        "\"delete_after_upload\":%s,\"delete_error\":%d}%s\n",
        s->network_check?"wifi_check":"upload", s->job, s->session, s->segment, s->stage, s->active?"true":"false",
        s->automatic?"true":"false", s->enabled?"true":"false", s->paused?"true":"false",
        s->sent, s->received, s->confirmed, s->size, s->error,
        s->delete_after_upload?"true":"false", s->delete_error, type?"":"}");
    return tail < 0 || (size_t)tail >= size-(size_t)n ? -ENOSPC : n+tail;
}

int upload_app_format_network(const struct upload_app_network *s, bool event,
                              uint32_t seq, uint32_t dropped, char *out, size_t size)
{
    int n = event ? snprintf(out, size,
        "{\"event\":\"wifi_check\",\"seq\":%u,\"lost\":%u,", seq, dropped) :
        snprintf(out, size, "{\"ok\":true,\"data\":{");
    if (n < 0 || (size_t)n >= size) { return -ENOSPC; }
    int tail = snprintf(out+n, size-n,
        "\"state\":\"%s\",\"scope\":\"wifi_dhcp\",\"job\":%u,\"checked_ms\":%u,"
        "\"ip\":\"%s\",\"error\":%d,\"cleanup_error\":%d}%s\n",
        s->state, s->job, s->checked_ms, s->ip, s->error, s->cleanup_error, event?"":"}");
    return tail < 0 || (size_t)tail >= size-(size_t)n ? -ENOSPC : n+tail;
}

static void enqueue(struct app_event *e)
{
    e->seq = (uint32_t)atomic_inc(&sequence)+1;
    if (k_msgq_put(&app_events, e, K_NO_WAIT)) {
        struct app_event discarded;
        if (!k_msgq_get(&app_events, &discarded, K_NO_WAIT)) { atomic_inc(&lost); }
        if (k_msgq_put(&app_events, e, K_NO_WAIT)) { atomic_inc(&lost); }
    }
}
void upload_app_publish(const char *type)
{
    struct upload_app_status status;
    upload_runtime_app_status(&status);
    upload_app_publish_result(type, &status);
}
void upload_app_publish_result(const char *type, const struct upload_app_status *status)
{
    struct app_event e = {.type=type, .value.upload=*status};
    enqueue(&e);
}
void upload_app_publish_network(const struct upload_app_network *status)
{
    struct app_event e = {.network=true, .value.wifi=*status};
    enqueue(&e);
}
void upload_app_resync(void) { atomic_set(&resync, 1); }

static int send_event(const struct app_event *e)
{
    char body[512];
    int n = e->network ? upload_app_format_network(&e->value.wifi, true, e->seq,
        atomic_get(&lost), body, sizeof(body)) :
        upload_app_format_status(&e->value.upload, e->type, e->seq,
        atomic_get(&lost), body, sizeof(body));
    return n < 0 ? n : ble_send((const uint8_t *)body, n);
}

void upload_app_poll(void)
{
    int64_t now = k_uptime_get();
    if (now-last_poll < 250) { return; }
    last_poll = now;
    if (!ble_is_connected() || !ble_is_notify_enabled()) {
        k_msgq_purge(&app_events);
        subscribed = pending_valid = previous_valid = false;
        return;
    }
    bool requested = atomic_cas(&resync, 1, 0);
    bool fresh = !subscribed || requested;
    subscribed = true;
    if (fresh) {
        /* A new subscriber needs current state, not stale connection history. */
        k_msgq_purge(&app_events);
        pending_valid = previous_valid = false;
        struct app_event e = {.network=true, .seq=(uint32_t)atomic_inc(&sequence)+1};
        upload_runtime_app_network(&e.value.wifi);
        if (send_event(&e)) { atomic_set(&resync, 1); return; }
    }
    if (!pending_valid) { pending_valid = !k_msgq_get(&app_events, &pending, K_NO_WAIT); }
    if (pending_valid) {
        if (!send_event(&pending)) { pending_valid = false; }
        return;
    }
    struct app_event e = {.type="progress"};
    upload_runtime_app_status(&e.value.upload);
    bool changed = !previous_valid || memcmp(&previous, &e.value.upload, sizeof(previous));
    bool transition = !previous_valid || previous.job!=e.value.upload.job ||
        previous.stage!=e.value.upload.stage || previous.active!=e.value.upload.active ||
        previous.enabled!=e.value.upload.enabled || previous.paused!=e.value.upload.paused;
    if (!changed || (!transition && now-last_progress < 1000)) { return; }
    e.type = previous_valid ? "progress" : "snapshot";
    e.seq = (uint32_t)atomic_inc(&sequence)+1;
    if (!send_event(&e)) {
        previous = e.value.upload; previous_valid = true; last_progress = now;
    }
}
