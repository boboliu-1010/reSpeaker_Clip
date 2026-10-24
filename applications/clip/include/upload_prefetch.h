/* Optional one-block SD producer. The upload worker owns this interface. */
#ifndef CLIP_UPLOAD_PREFETCH_H
#define CLIP_UPLOAD_PREFETCH_H
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

struct upload_prefetch;
struct upload_prefetch_stats {
    uint64_t read_us, seek_us, wait_us;
    uint32_t requests, reads, deliveries, fallbacks, discarded;
    uint32_t stack_size, stack_peak;
    int start_error, read_error, close_error;
    bool started;
};
int upload_prefetch_open(struct upload_prefetch **out, const char *path,
                         uint32_t size, unsigned int priority, int (*check)(void));
/* 1: swaps the completed buffer with the caller's 8192-byte buffer.
 * 0: optional producer unavailable; caller must perform its synchronous read.
 * Negative: cancellation/deadline. No caller buffer is touched on 0/error. */
int upload_prefetch_take(struct upload_prefetch *p, uint32_t offset,
                         uint8_t **buffer, uint32_t *length);
/* Join before closing/freeing. Never abort a thread inside a filesystem call.
 * On a join/free error, preserve *p so ownership is not silently discarded. */
int upload_prefetch_close(struct upload_prefetch **p, struct upload_prefetch_stats *out);
#endif
