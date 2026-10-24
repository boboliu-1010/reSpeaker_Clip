#include <zephyr/kernel.h>
#include <zephyr/fs/fs.h>
#include <zephyr/sys/atomic.h>
#include <errno.h>
#include <string.h>
#include "upload_prefetch.h"

#define BLOCK_BYTES 8192U
#define STACK_BYTES 4096U

struct upload_prefetch {
    struct k_thread thread;
    k_thread_stack_t *stack;
    struct fs_file_t file;
    struct k_sem request, ready;
    atomic_t stop;
    uint8_t *buffer;
    uint32_t size, requested, length;
    int result;
    int (*check)(void);
    bool pending, opened, failed;
    uint64_t read_ticks, seek_ticks, wait_ticks;
    struct upload_prefetch_stats stats;
};

/* request/ready transfer ownership of buffer/request/result. Only the producer
 * touches its file handle; retransmission reads keep the uploader's handle. */
static void producer(void *arg, void *unused1, void *unused2)
{
    ARG_UNUSED(unused1); ARG_UNUSED(unused2);
    struct upload_prefetch *p = arg;
    uint32_t position = 0;
    for (;;) {
        k_sem_take(&p->request, K_FOREVER);
        if (atomic_get(&p->stop)) { break; }
        p->length = 0;
        int ret = p->check();
        if (!ret && position != p->requested) {
            uint64_t began = k_uptime_ticks();
            ret = fs_seek(&p->file, p->requested, FS_SEEK_SET);
            p->seek_ticks += k_uptime_ticks() - began;
            if (!ret) { position = p->requested; }
        }
        uint32_t wanted = MIN(BLOCK_BYTES, p->size - p->requested);
        while (!ret && p->length < wanted && !atomic_get(&p->stop)) {
            ret = p->check();
            if (ret) { break; }
            uint64_t began = k_uptime_ticks();
            ssize_t n = fs_read(&p->file, p->buffer + p->length, wanted - p->length);
            p->read_ticks += k_uptime_ticks() - began;
            p->stats.reads++;
            if (n <= 0) { ret = n < 0 ? (int)n : -EIO; break; }
            p->length += (uint32_t)n;
            position += (uint32_t)n;
        }
        if (atomic_get(&p->stop)) { ret = -ECANCELED; }
        p->result = ret;
        k_sem_give(&p->ready);
    }
}

int upload_prefetch_open(struct upload_prefetch **out, const char *path,
                         uint32_t size, unsigned int priority, int (*check)(void))
{
    if (!out || *out || !path || !check || !size || priority < 6 || priority > 8) { return -EINVAL; }
    struct upload_prefetch *p = k_malloc(sizeof(*p));
    if (!p) { return -ENOMEM; }
    memset(p, 0, sizeof(*p));
    p->size = size; p->check = check;
    p->buffer = k_malloc(BLOCK_BYTES);
    if (!p->buffer) { k_free(p); return -ENOMEM; }
    p->stack = k_thread_stack_alloc(STACK_BYTES, 0);
    if (!p->stack) { k_free(p->buffer); k_free(p); return -ENOMEM; }
    fs_file_t_init(&p->file);
    int ret = fs_open(&p->file, path, FS_O_READ);
    if (ret) {
        k_thread_stack_free(p->stack);
        k_free(p->buffer); k_free(p);
        return ret;
    }
    p->opened = true;
    k_sem_init(&p->request, 0, 1); k_sem_init(&p->ready, 0, 1);
    /* Bounded experiment around the priority-7 upload worker. Smaller values
     * preempt it so a new SD request can start before the current block drains. */
    k_thread_create(&p->thread, p->stack, STACK_BYTES, producer, p, NULL, NULL,
                    (int)priority, 0, K_NO_WAIT);
    k_thread_name_set(&p->thread, "upload_sd");
    p->stats.started = true; p->stats.stack_size = STACK_BYTES;
    *out = p;
    return 0;
}

static void request(struct upload_prefetch *p, uint32_t offset)
{
    p->requested = offset; p->pending = true;
    p->stats.requests++;
    k_sem_give(&p->request);
}

int upload_prefetch_take(struct upload_prefetch *p, uint32_t offset,
                         uint8_t **buffer, uint32_t *length)
{
    if (!p || !buffer || !*buffer || !length || offset >= p->size) { return -EINVAL; }
    int ret = p->check();
    if (ret) { return ret; }
    if (p->failed) { p->stats.fallbacks++; return 0; }
    if (p->pending && p->requested != offset) {
        /* A retransmission/jump must not wait for an unrelated future block.
         * Replan only after the producer relinquishes its slot. */
        if (k_sem_take(&p->ready, K_NO_WAIT)) { p->stats.fallbacks++; return 0; }
        p->pending = false;
        p->stats.discarded++;
        if (p->result && p->result != -ECANCELED) {
            p->failed = true; p->stats.read_error = p->result;
            p->stats.fallbacks++; return 0;
        }
    }
    if (!p->pending) { request(p, offset); }
    uint64_t began = k_uptime_ticks();
    while ((ret = k_sem_take(&p->ready, K_MSEC(20))) != 0) {
        int cancelled = p->check();
        if (cancelled) {
            p->wait_ticks += k_uptime_ticks() - began;
            return cancelled;
        }
    }
    p->wait_ticks += k_uptime_ticks() - began;
    p->pending = false;
    ret = p->check();
    if (ret) { return ret; }
    if (p->result) {
        p->failed = true; p->stats.read_error = p->result;
        p->stats.fallbacks++; return 0;
    }
    uint8_t *previous = *buffer;
    *buffer = p->buffer; p->buffer = previous; *length = p->length;
    p->stats.deliveries++;
    uint32_t next = offset + p->length;
    if (next < p->size) { request(p, next); }
    return 1;
}

int upload_prefetch_close(struct upload_prefetch **ptr, struct upload_prefetch_stats *out)
{
    if (!ptr || !*ptr || !out) { return -EINVAL; }
    struct upload_prefetch *p = *ptr;
    atomic_set(&p->stop, 1);
    k_sem_give(&p->request);
    int ret = k_thread_join(&p->thread, K_FOREVER);
    if (ret) { return ret; }
    if (p->opened) {
        p->stats.close_error = fs_close(&p->file);
        p->opened = false;
    }
    size_t unused;
    if (!k_thread_stack_space_get(&p->thread, &unused) && unused <= STACK_BYTES) {
        p->stats.stack_peak = STACK_BYTES - unused;
    }
    p->stats.read_us = k_ticks_to_us_floor64(p->read_ticks);
    p->stats.seek_us = k_ticks_to_us_floor64(p->seek_ticks);
    p->stats.wait_us = k_ticks_to_us_floor64(p->wait_ticks);
    *out = p->stats;
    ret = k_thread_stack_free(p->stack);
    if (ret) { return ret; }
    k_free(p->buffer); k_free(p);
    *ptr = NULL;
    return out->close_error;
}
