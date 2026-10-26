/* A successful upload nominates one session. No historical uploaded sweep.
 * The durable intent and move keep partially deleted sessions out of REC. */
#include "upload_cleanup.h"
#include "upload_scan.h"
#include "upload_state.h"
#include "storage.h"
#include <zephyr/sys/crc.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define TRASH "/SD:/UPDEL"
#define INTENT "delete.bin"
#define MAGIC 0x314c4455U
struct intent {
    uint32_t magic, version, count;
    char session[16];
    uint8_t destination[32];
    uint32_t crc;
};
struct verification {
    const char *session;
    const uint8_t *destination;
    uint32_t count, maximum;
    uint64_t bytes;
    bool incomplete;
};
static bool valid_id(const char *id)
{
    if (!id || strlen(id)!=14) { return false; }
    for (unsigned i=0;i<14;i++) { if (id[i]<'0' || id[i]>'9') { return false; } }
    return true;
}
static int path_join(char out[STORAGE_PATH_MAX], const char *dir, const char *name)
{
    int n=snprintf(out,STORAGE_PATH_MAX,"%s/%s",dir,name);
    return n<0 || n>=STORAGE_PATH_MAX ? -ENAMETOOLONG : 0;
}
static int verify_segment(const char *id, uint32_t number, uint32_t size,
                          bool sealed, void *context)
{
    struct verification *v=context;
    if (strcmp(id,v->session) || !sealed || !size) { v->incomplete=true; return 0; }
    struct upload_file_record r;
    int ret=upload_state_load(id,number,&r);
    if (ret && ret!=-ENOENT && ret!=-EBADMSG) { return ret; }
    if (ret || r.state!=UPLOAD_STORED || r.size!=size || r.confirmed!=size || r.last_error ||
        memcmp(r.destination_sha256,v->destination,32)) { v->incomplete=true; return 0; }
    v->count++; v->bytes+=size;
    if (number>v->maximum) { v->maximum=number; }
    return 0;
}
static int write_intent(const char *dir, struct intent *intent)
{
    char path[STORAGE_PATH_MAX];
    int ret=path_join(path,dir,INTENT);
    if (ret) { return ret; }
    intent->crc=crc32_ieee((const uint8_t *)intent,offsetof(struct intent,crc));
    struct fs_file_t f;fs_file_t_init(&f);
    ret=fs_open(&f,path,FS_O_CREATE|FS_O_WRITE|FS_O_TRUNC);
    if (ret) { return ret; }
    ssize_t n=fs_write(&f,intent,sizeof(*intent));
    ret=n<0 ? (int)n : n!=(ssize_t)sizeof(*intent) ? -EIO : fs_sync(&f);
    int closed=fs_close(&f);
    return ret ? ret : closed;
}
static int read_intent(const char *dir, const char *id)
{
    char path[STORAGE_PATH_MAX];struct intent intent;
    int ret=path_join(path,dir,INTENT);
    if (ret) { return ret; }
    struct fs_file_t f;fs_file_t_init(&f);
    ret=fs_open(&f,path,FS_O_READ);
    if (ret) { return ret; }
    ssize_t n=fs_read(&f,&intent,sizeof(intent));
    int closed=fs_close(&f);
    if (n<0) { return n; }
    if (closed) { return closed; }
    if (n!=(ssize_t)sizeof(intent) || intent.magic!=MAGIC || intent.version!=1 || !intent.count ||
        memcmp(intent.session,id,15) ||
        intent.crc!=crc32_ieee((const uint8_t *)&intent,offsetof(struct intent,crc))) { return -EBADMSG; }
    return 0;
}
/* At most a session and its numeric group subdirectory: never recurse through
 * arbitrary trees or retain the outer trash directory handle. Intent goes last. */
static int remove_tree(const char *path, unsigned depth, int (*check)(void))
{
    /* Reopen after each removal: FAT iteration offsets need not survive unlink. */
    for (;;) {
        int ret=check(); if (ret) { return ret; }
        struct fs_dir_t dir; struct fs_dirent entry; fs_dir_t_init(&dir);
        ret=fs_opendir(&dir,path); if (ret) { return ret; }
        bool found=false;
        while (!(ret=check()) && !(ret=fs_readdir(&dir,&entry)) && entry.name[0]) {
            if (!strcmp(entry.name,".") || !strcmp(entry.name,"..") ||
                (!depth && !strcmp(entry.name,INTENT))) { continue; }
            found=true;break;
        }
        int closed=fs_closedir(&dir); if (!ret) { ret=closed; }
        if (ret) { return ret; }
        if (!found) { break; }
        char child[STORAGE_PATH_MAX]; ret=path_join(child,path,entry.name);
        if (ret) { return ret; }
        if (entry.type==FS_DIR_ENTRY_DIR) {
            if (depth) { return -EINVAL; }
            for (const char *p=entry.name;*p;p++) { if (*p<'0' || *p>'9') { return -EINVAL; } }
            ret=remove_tree(child,depth+1,check);
        } else { ret=fs_unlink(child); }
        if (ret) { return ret; }
    }
    int ret=check(); if (ret) { return ret; }
    if (!depth) {
        char marker[STORAGE_PATH_MAX]; ret=path_join(marker,path,INTENT);
        if (!ret) { ret=fs_unlink(marker); }
    }
    return ret ? ret : fs_unlink(path);
}
int upload_cleanup_pending(const char *id)
{
    if (!valid_id(id)) { return 0; }
    char path[STORAGE_PATH_MAX];
    int ret=storage_build_session_metadata_path(id,path,sizeof(path));
    if (ret) { return 0; }
    char *tail=strrchr(path,'/'); if (!tail) { return 0; } *tail=0;
    return read_intent(path,id)==0;
}
static int remove_staged(const char *id, int (*check)(void))
{
    char path[STORAGE_PATH_MAX];int ret=path_join(path,TRASH,id);
    if (ret) { return ret; }
    ret=read_intent(path,id);
    if (ret==-ENOENT) {
        /* Power loss after the final marker unlink: only remove an empty dir. */
        return fs_unlink(path);
    }
    return ret ? ret : remove_tree(path,0,check);
}
int upload_cleanup_session(const char *id, const uint8_t destination[32], int (*check)(void))
{
    if (!valid_id(id) || !destination || !check) { return -EINVAL; }
    int ret=check();if (ret) { return ret; }
    struct storage_session_info info;
    ret=storage_get_session_info(id,&info);
    if (ret) { return ret; }
    if (!info.file_count || !info.total_bytes) { return 0; }
    struct verification v={.session=id,.destination=destination};
    ret=upload_scan_session(id,verify_segment,&v,check);
    if (ret) { return ret; }
    if (v.incomplete || v.count!=info.file_count || v.maximum!=v.count || v.bytes!=info.total_bytes) { return 0; }
    char original[STORAGE_PATH_MAX],staged[STORAGE_PATH_MAX];
    ret=storage_build_session_metadata_path(id,original,sizeof(original));
    if (ret) { return ret; }
    char *tail=strrchr(original,'/');if (!tail) { return -EINVAL; }*tail=0;
    ret=path_join(staged,TRASH,id);if (ret) { return ret; }
    struct fs_dirent entry;
    ret=fs_stat(staged,&entry);
    if (!ret) { return -EEXIST; }
    if (ret!=-ENOENT) { return ret; }
    ret=fs_mkdir(TRASH);if (ret && ret!=-EEXIST) { return ret; }
    struct intent intent={.magic=MAGIC,.version=1,.count=v.count};
    strcpy(intent.session,id);memcpy(intent.destination,destination,32);
    ret=write_intent(original,&intent);
    if (!ret) { ret=check(); }
    if (!ret) { ret=fs_rename(original,staged); }
    if (!ret) { ret=remove_staged(id,check); }
    return ret ? ret : 1;
}
int upload_cleanup_resume(int (*check)(void))
{
    if (!check) { return -EINVAL; }
    int ret=storage_ensure_mounted();if (ret) { return ret; }
    for (;;) {
        ret=check();if (ret) { return ret; }
        struct fs_dir_t dir;struct fs_dirent entry;fs_dir_t_init(&dir);
        ret=fs_opendir(&dir,TRASH);
        if (ret==-ENOENT) { return 0; }
        if (ret) { return ret; }
        char id[16]={0};
        while (!(ret=check()) && !(ret=fs_readdir(&dir,&entry)) && entry.name[0]) {
            if (entry.type==FS_DIR_ENTRY_DIR && valid_id(entry.name)) { strcpy(id,entry.name);break; }
        }
        int closed=fs_closedir(&dir);if (!ret) { ret=closed; }
        if (ret || !id[0]) { return ret; }
        ret=remove_staged(id,check);if (ret) { return ret; }
    }
}
