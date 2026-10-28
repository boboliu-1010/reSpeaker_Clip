#include "recording_origin.h"
#include "storage.h"
#include <zephyr/sys/crc.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>

#define ORIGIN_MAGIC 0x314f4142U
struct origin_record {
    uint32_t magic, version, epoch;
    char session[14], binding[32];
    uint8_t reserved[2];
    uint32_t crc;
};
BUILD_ASSERT(sizeof(struct origin_record) == 64 && offsetof(struct origin_record, crc) == 60,
             "Recording origin v1 layout changed");
BUILD_ASSERT(__BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__, "Recording origin v1 is little endian");

static bool origin_identity(const char *session, const char *binding, uint32_t epoch)
{
    if (!session || strlen(session) != 14 || !binding) { return false; }
    for (const char *p = session; *p; p++) { if (*p < '0' || *p > '9') { return false; } }
    if (!*binding) { return epoch == 0; }
    if (strlen(binding) != 32 || !epoch) { return false; }
    for (const char *p = binding; *p; p++) {
        if (!(*p >= '0' && *p <= '9') && !(*p >= 'a' && *p <= 'f')) { return false; }
    }
    return true;
}

static int origin_path(const char *session, const char *name, char path[STORAGE_PATH_MAX])
{
    int ret = storage_build_session_metadata_path(session, path, STORAGE_PATH_MAX);
    if (ret) { return ret; }
    char *tail = strrchr(path, '/');
    if (!tail) { return -EINVAL; }
    size_t available = STORAGE_PATH_MAX - (++tail - path);
    int n = snprintf(tail, available, "%s", name);
    return n < 0 || (size_t)n >= available ? -ENAMETOOLONG : 0;
}

/* New storage sessions already contain an empty "0" chunk group. Nothing
 * else may be adopted: an old recording can survive without session.json. */
static int origin_empty_session(const char *metadata)
{
    char path[STORAGE_PATH_MAX];
    int n = snprintf(path, sizeof(path), "%s", metadata);
    if (n < 0 || (size_t)n >= sizeof(path)) { return -EEXIST; }
    char *tail = strrchr(path, '/');
    if (!tail) { return -EEXIST; }
    *tail = 0;
    struct fs_dir_t directory;
    struct fs_dirent entry;
    fs_dir_t_init(&directory);
    int ret = fs_opendir(&directory, path);
    if (ret) { return -EEXIST; }
    bool group = false;
    while (!(ret = fs_readdir(&directory, &entry)) && entry.name[0]) {
        if (!strcmp(entry.name, ".") || !strcmp(entry.name, "..")) { continue; }
        if (!strcmp(entry.name, "0") && entry.type == FS_DIR_ENTRY_DIR) { group = true; }
        else { ret = -EEXIST; break; }
    }
    int closed = fs_closedir(&directory);
    if (ret || closed) { return -EEXIST; }
    if (!group) { return 0; }
    size_t used = strlen(path);
    if (used + 3 > sizeof(path)) { return -EEXIST; }
    memcpy(path + used, "/0", 3);
    fs_dir_t_init(&directory);
    if (fs_opendir(&directory, path)) { return -EEXIST; }
    while (!(ret = fs_readdir(&directory, &entry)) && entry.name[0]) {
        if (!strcmp(entry.name, ".") || !strcmp(entry.name, "..")) { continue; }
        ret = -EEXIST;
        break;
    }
    closed = fs_closedir(&directory);
    return ret || closed ? -EEXIST : 0;
}

int recording_origin_create(const char *session, const char *binding, uint32_t epoch)
{
    if (!origin_identity(session, binding, epoch)) { return -EINVAL; }
    char metadata[STORAGE_PATH_MAX], path[STORAGE_PATH_MAX], temporary[STORAGE_PATH_MAX];
    int ret = storage_build_session_metadata_path(session, metadata, sizeof(metadata));
    if (!ret) { ret = origin_path(session, "binding.bin", path); }
    if (!ret) { ret = origin_path(session, "binding.tmp", temporary); }
    if (ret) { return ret; }
    struct origin_record record = {.magic = ORIGIN_MAGIC, .version = 1, .epoch = epoch};
    memcpy(record.session, session, 14);
    if (*binding) { memcpy(record.binding, binding, 32); }
    record.crc = crc32_ieee((const uint8_t *)&record, offsetof(struct origin_record, crc));
    struct fs_dirent entry;
    struct fs_file_t file;
    fs_file_t_init(&file);
    storage_session_json_lock();
    /* An old session or an existing origin can never be relabeled, including
     * an unknown legacy recording and a clock/session-ID collision. */
    ret = fs_stat(metadata, &entry);
    if (!ret) { ret = -EEXIST; goto done; }
    if (ret != -ENOENT) { ret = -EEXIST; goto done; }
    ret = fs_stat(path, &entry);
    if (!ret) { ret = -EEXIST; goto done; }
    if (ret != -ENOENT) { ret = -EEXIST; goto done; }
    ret = origin_empty_session(metadata);
    if (ret) { goto done; }
    ret = fs_open(&file, temporary, FS_O_CREATE | FS_O_WRITE | FS_O_TRUNC);
    if (!ret) {
        ssize_t n = fs_write(&file, &record, sizeof(record));
        ret = n < 0 ? (int)n : n != (ssize_t)sizeof(record) ? -EIO : fs_sync(&file);
        int closed = fs_close(&file);
        if (!ret) { ret = closed; }
    }
    if (!ret) { ret = fs_rename(temporary, path); }
    if (ret) { (void)fs_unlink(temporary); }
done:
    storage_session_json_unlock();
    return ret;
}

bool recording_origin_matches(const char *session, const char *binding, uint32_t epoch)
{
    if (!origin_identity(session, binding, epoch) || !*binding) { return false; }
    char path[STORAGE_PATH_MAX];
    if (origin_path(session, "binding.bin", path)) { return false; }
    struct origin_record record;
    struct fs_file_t file;
    fs_file_t_init(&file);
    storage_session_json_lock();
    int ret = fs_open(&file, path, FS_O_READ);
    bool matches = false;
    if (!ret) {
        ssize_t n = fs_read(&file, &record, sizeof(record));
        uint8_t extra;
        ssize_t tail = n == (ssize_t)sizeof(record) ? fs_read(&file, &extra, 1) : 0;
        int closed = fs_close(&file);
        matches = n == (ssize_t)sizeof(record) && !tail && !closed &&
            record.magic == ORIGIN_MAGIC && record.version == 1 && record.epoch == epoch &&
            !memcmp(record.session, session, 14) && !memcmp(record.binding, binding, 32) &&
            !record.reserved[0] && !record.reserved[1] &&
            record.crc == crc32_ieee((const uint8_t *)&record, offsetof(struct origin_record, crc));
    }
    storage_session_json_unlock();
    return matches;
}
