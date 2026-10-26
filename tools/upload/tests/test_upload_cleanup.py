"""Exercise the actual C deletion transaction against files and injected faults."""
from pathlib import Path
import subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[3]
class CleanupTest(unittest.TestCase):
    def test_whole_session_verification_and_interrupted_cleanup(self):
        code=r'''
#define _DEFAULT_SOURCE
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <dirent.h>
#include <sys/stat.h>
#include "upload_state.h"
#include "upload_scan.h"
#define STORAGE_PATH_MAX 128
#define FS_DIR_ENTRY_DIR 1
#define FS_DIR_ENTRY_FILE 2
#define FS_O_READ 1
#define FS_O_WRITE 2
#define FS_O_CREATE 4
#define FS_O_TRUNC 8
struct fs_file_t {int fd;};
struct fs_dir_t {DIR *dir;char path[128];};
struct fs_dirent {int type;size_t size;char name[256];};
struct storage_session_info {uint32_t file_count;uint64_t total_bytes;};
static const char *sid="20261026090000";
static uint8_t dest[32];
static struct upload_file_record records[3];
static bool sealed=true,cancelled,cancel_on_unlink;
static int journal_error,write_error,sync_error,rename_error,unlink_error,close_error;
static int opened,renames,deletions,expected_count=2;
static uint64_t expected_bytes=30;
static const char *root;
static void physical(const char *p,char out[512]){assert(!strncmp(p,"/SD:",4));snprintf(out,512,"%s%s",root,p+4);}
static int check(void){return cancelled?-ECANCELED:0;}
static uint32_t crc32_ieee(const uint8_t*p,size_t n){uint32_t c=~0u;while(n--){c^=*p++;for(int i=0;i<8;i++)c=(c>>1)^((c&1)?0xedb88320u:0);}return ~c;}
static int storage_ensure_mounted(void){return 0;}
static int storage_get_session_info(const char *id,struct storage_session_info *out){assert(!strcmp(id,sid));out->file_count=expected_count;out->total_bytes=expected_bytes;return 0;}
static int storage_build_session_metadata_path(const char *id,char *out,size_t n){if(strcmp(id,sid))return -EINVAL;snprintf(out,n,"/SD:/REC/%s/session.json",id);return 0;}
int upload_state_load(const char *id,uint32_t number,struct upload_file_record *out){assert(!strcmp(id,sid));if(journal_error)return journal_error;if(number>2)return -ENOENT;*out=records[number];return 0;}
int upload_scan_session(const char*id,upload_visit_fn visit,void *context,int(*cancel)(void)){
 for(unsigned i=1;i<=2;i++){if(cancel())return cancel();int ret=visit(id,i,i*10,sealed,context);if(ret)return ret;}return 0;
}
static int fs_stat(const char *p,struct fs_dirent *out){char path[512];physical(p,path);struct stat st;if(stat(path,&st))return -errno;out->type=S_ISDIR(st.st_mode)?FS_DIR_ENTRY_DIR:FS_DIR_ENTRY_FILE;out->size=st.st_size;return 0;}
static int fs_mkdir(const char*p){char path[512];physical(p,path);return mkdir(path,0700)?-errno:0;}
static int fs_rename(const char*a,const char*b){if(rename_error)return -EIO;char x[512],y[512];physical(a,x);physical(b,y);if(rename(x,y))return -errno;renames++;return 0;}
static int fs_unlink(const char*p){if(unlink_error)return -EIO;char path[512];physical(p,path);struct stat st;if(stat(path,&st))return -errno;int ret=S_ISDIR(st.st_mode)?rmdir(path):unlink(path);if(ret)return -errno;deletions++;if(cancel_on_unlink)cancelled=true;return 0;}
static void fs_file_t_init(struct fs_file_t*f){f->fd=-1;}
static int fs_open(struct fs_file_t*f,const char*p,int flags){char path[512];physical(p,path);int mode=flags&FS_O_WRITE?O_WRONLY:O_RDONLY;if(flags&FS_O_CREATE)mode|=O_CREAT;if(flags&FS_O_TRUNC)mode|=O_TRUNC;f->fd=open(path,mode,0600);if(f->fd<0)return -errno;opened++;return 0;}
static ssize_t fs_write(struct fs_file_t*f,const void*p,size_t n){if(write_error)return -EIO;ssize_t r=write(f->fd,p,n);return r<0?-errno:r;}
static ssize_t fs_read(struct fs_file_t*f,void*p,size_t n){ssize_t r=read(f->fd,p,n);return r<0?-errno:r;}
static int fs_sync(struct fs_file_t*f){return sync_error?-EIO:fsync(f->fd);}
static int fs_close(struct fs_file_t*f){int ret=close(f->fd);opened--;return close_error?-EIO:ret;}
static void fs_dir_t_init(struct fs_dir_t*d){d->dir=NULL;}
static int fs_opendir(struct fs_dir_t*d,const char*p){char path[512];physical(p,path);d->dir=opendir(path);if(!d->dir)return -errno;strcpy(d->path,p);opened++;return 0;}
static int fs_readdir(struct fs_dir_t*d,struct fs_dirent*out){struct dirent*e;while((e=readdir(d->dir))&&(!strcmp(e->d_name,".")||!strcmp(e->d_name,".."))){}if(!e){out->name[0]=0;return 0;}strcpy(out->name,e->d_name);char path[512],base[512];physical(d->path,base);int n=snprintf(path,sizeof(path),"%s/%s",base,e->d_name);assert(n>0&&n<(int)sizeof(path));struct stat st;assert(!stat(path,&st));out->type=S_ISDIR(st.st_mode)?FS_DIR_ENTRY_DIR:FS_DIR_ENTRY_FILE;out->size=st.st_size;return 0;}
static int fs_closedir(struct fs_dir_t*d){int r=closedir(d->dir);opened--;return r;}
'''
        source=(ROOT/'applications/clip/src/upload_cleanup.c').read_text()
        code+='\n'.join(line for line in source.splitlines() if not line.startswith('#include'))
        code+=r'''
static bool exists(const char *p){char path[512];physical(p,path);return !access(path,F_OK);}
static void make(const char*p,size_t size){char path[512];physical(p,path);FILE*f=fopen(path,"w");assert(f);for(size_t i=0;i<size;i++)assert(fputc('x',f)!=EOF);assert(!fclose(f));}
static void setup(void){
 assert(!fs_mkdir("/SD:/REC")||errno==EEXIST);
 char path[128];snprintf(path,sizeof(path),"/SD:/REC/%s",sid);assert(!fs_mkdir(path));strcat(path,"/0");assert(!fs_mkdir(path));
 make("/SD:/REC/20261026090000/session.json",10);make("/SD:/REC/20261026090000/0/0001.opus",10);make("/SD:/REC/20261026090000/0/0002.opus",20);
 for(unsigned i=1;i<=2;i++){records[i]=(struct upload_file_record){.size=i*10,.confirmed=i*10,.state=UPLOAD_STORED};memcpy(records[i].destination_sha256,dest,32);}
}
int main(int argc,char **argv){assert(argc==2);root=argv[1];memset(dest,0x22,32);setup();
 assert(upload_cleanup_session("../unsafe",dest,check)==-EINVAL);
 /* Resume never sweeps historical completed recordings. */
 assert(!upload_cleanup_resume(check)&&exists("/SD:/REC/20261026090000/0/0001.opus"));
 sealed=false;assert(!upload_cleanup_session(sid,dest,check));sealed=true;
 records[1].state=UPLOAD_PARTIAL;records[1].confirmed=5;assert(!upload_cleanup_session(sid,dest,check));records[1].state=UPLOAD_STORED;records[1].confirmed=10;
 records[1].destination_sha256[0]^=1;assert(!upload_cleanup_session(sid,dest,check));records[1].destination_sha256[0]^=1;
 journal_error=-EBADMSG;assert(!upload_cleanup_session(sid,dest,check));journal_error=-EIO;assert(upload_cleanup_session(sid,dest,check)==-EIO);journal_error=0;
 expected_count=3;assert(!upload_cleanup_session(sid,dest,check));expected_count=2;
 expected_bytes=31;assert(!upload_cleanup_session(sid,dest,check));expected_bytes=30;
 assert(!renames&&!deletions&&!opened);
 write_error=1;assert(upload_cleanup_session(sid,dest,check)==-EIO);write_error=0;
 sync_error=1;assert(upload_cleanup_session(sid,dest,check)==-EIO);sync_error=0;
 close_error=1;assert(upload_cleanup_session(sid,dest,check)==-EIO);close_error=0;
 assert(!renames&&!deletions&&!opened);
 rename_error=1;assert(upload_cleanup_session(sid,dest,check)==-EIO);rename_error=0;
 assert(upload_cleanup_pending(sid));assert(exists("/SD:/REC/20261026090000/0/0002.opus"));
 /* Failed physical cleanup has moved the whole recording out of REC. */
 unlink_error=1;assert(upload_cleanup_session(sid,dest,check)==-EIO);unlink_error=0;
 assert(renames==1&&!exists("/SD:/REC/20261026090000"));
 cancel_on_unlink=true;assert(upload_cleanup_resume(check)==-ECANCELED);cancel_on_unlink=false;cancelled=false;
 /* Model reset: only persisted staging intent is needed; journals can be gone. */
 memset(records,0,sizeof(records));assert(!upload_cleanup_resume(check));
 assert(!exists("/SD:/UPDEL/20261026090000")&&!opened);
 setup();assert(upload_cleanup_session(sid,dest,check)==1);assert(!exists("/SD:/REC/20261026090000")&&!opened);
 /* Empty stage after marker removal is harmless; bad nonempty intent is kept. */
 assert(!fs_mkdir("/SD:/UPDEL/20261026090000"));assert(!upload_cleanup_resume(check));
 assert(!fs_mkdir("/SD:/UPDEL/20261026090000"));make("/SD:/UPDEL/20261026090000/delete.bin",3);make("/SD:/UPDEL/20261026090000/keep.opus",10);
 assert(upload_cleanup_resume(check)==-EBADMSG&&exists("/SD:/UPDEL/20261026090000/keep.opus")&&!opened);
 return 0;}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'fs').mkdir();(p/'test.c').write_text(code)
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I'+str(ROOT/'applications/clip/include'),str(p/'test.c'),'-o',str(p/'test')],check=True)
            subprocess.run([str(p/'test'),str(p/'fs')],check=True)
