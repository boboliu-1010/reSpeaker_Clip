"""Immutable Boa recording provenance with real host filesystem and fault injection."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_auto_upload import without_includes

ROOT = Path(__file__).resolve().parents[3]

PRELUDE = r'''
#define CONFIG_BOA_USER_BINDING 1
#include "upload_config.h"
#include "upload_state.h"
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <dirent.h>
#include "recording_origin.h"
#define BUILD_ASSERT(c,m) _Static_assert(c,m)
#define STORAGE_PATH_MAX 256
#define FS_O_READ 1
#define FS_O_WRITE 2
#define FS_O_CREATE 4
#define FS_O_TRUNC 8
struct fs_file_t {int fd;};
#define FS_DIR_ENTRY_FILE 1
#define FS_DIR_ENTRY_DIR 2
struct fs_dirent {int type;char name[256];};
struct fs_dir_t {DIR *dir;};
void fs_dir_t_init(struct fs_dir_t*d){d->dir=NULL;}
int fs_opendir(struct fs_dir_t*d,const char*p){d->dir=opendir(p);return d->dir?0:-errno;}
int fs_readdir(struct fs_dir_t*d,struct fs_dirent*e){struct dirent*entry;do{errno=0;entry=readdir(d->dir);}while(entry&&(!strcmp(entry->d_name,".")||!strcmp(entry->d_name,"..")));if(!entry){e->name[0]=0;return errno?-errno:0;}snprintf(e->name,sizeof(e->name),"%s",entry->d_name);e->type=entry->d_type==DT_DIR?FS_DIR_ENTRY_DIR:FS_DIR_ENTRY_FILE;return 0;}
int fs_closedir(struct fs_dir_t*d){int n=closedir(d->dir);d->dir=NULL;return n?-errno:0;}
static const char *directory;
static int sync_error,close_error,write_short,rename_error,stat_error;
static bool locked;
static uint32_t crc32_ieee(const uint8_t*p,size_t n){uint32_t c=~0u;while(n--){c^=*p++;for(int i=0;i<8;i++)c=(c>>1)^((c&1)?0xedb88320u:0);}return ~c;}
static void storage_session_json_lock(void){assert(!locked);locked=true;}
static void storage_session_json_unlock(void){assert(locked);locked=false;}
static int storage_build_session_metadata_path(const char*s,char*out,size_t n){int k=snprintf(out,n,"%s/%s/session.json",directory,s);return k<0||(size_t)k>=n?-ENAMETOOLONG:0;}
static void fs_file_t_init(struct fs_file_t*f){f->fd=-1;}
static int fs_stat(const char*p,struct fs_dirent*e){struct stat st;if(stat_error)return -EIO;if(stat(p,&st))return -errno;e->type=S_ISDIR(st.st_mode)?FS_DIR_ENTRY_DIR:FS_DIR_ENTRY_FILE;return 0;}
static int fs_open(struct fs_file_t*f,const char*p,int flags){assert(locked);int m=flags&FS_O_WRITE?O_WRONLY:O_RDONLY;if(flags&FS_O_CREATE)m|=O_CREAT;if(flags&FS_O_TRUNC)m|=O_TRUNC;f->fd=open(p,m,0600);return f->fd<0?-errno:0;}
static ssize_t fs_read(struct fs_file_t*f,void*out,size_t n){ssize_t k=read(f->fd,out,n);return k<0?-errno:k;}
static ssize_t fs_write(struct fs_file_t*f,const void*p,size_t n){ssize_t k=write(f->fd,p,write_short?n/2:n);return k<0?-errno:k;}
static int fs_sync(struct fs_file_t*f){return sync_error?-EIO:fsync(f->fd);}
static int fs_close(struct fs_file_t*f){int k=close(f->fd);f->fd=-1;return close_error?-EIO:k;}
static int fs_rename(const char*from,const char*to){assert(locked);return rename_error?-EIO:rename(from,to)?-errno:0;}
static int fs_unlink(const char*p){assert(strstr(p,"binding.tmp"));return unlink(p)?-errno:0;}
'''

MAIN = r'''
static const char *binding="0123456789abcdef0123456789abcdef",*other="1123456789abcdef0123456789abcdef";
static void session_dir(const char*s){char path[256];snprintf(path,sizeof(path),"%s/%s",directory,s);assert(!mkdir(path,0700));strcat(path,"/0");assert(!mkdir(path,0700));}
static void old_recording(const char*s){char path[256];snprintf(path,sizeof(path),"%s/%s/session.json",directory,s);int fd=open(path,O_WRONLY|O_CREAT,0600);assert(fd>=0&&write(fd,"old",3)==3&&!close(fd));}
int main(int argc,char**argv){
 assert(argc==2);directory=argv[1];const char*s="20261028000000";session_dir(s);
 /* Existing legacy audio is retained; presence never grants a new origin. */
 old_recording(s);assert(!recording_origin_matches(s,binding,1));
 assert(recording_origin_create(s,binding,1)==-EEXIST);assert(!recording_origin_matches(s,binding,1));
 char metadata[256];storage_build_session_metadata_path(s,metadata,sizeof(metadata));struct stat st;assert(!stat(metadata,&st)&&st.st_size==3);
 s="20261028000001";session_dir(s);assert(!recording_origin_create(s,binding,1));
 assert(recording_origin_matches(s,binding,1)&&!recording_origin_matches(s,other,1)&&!recording_origin_matches(s,binding,2));
 assert(recording_origin_create(s,other,2)==-EEXIST);assert(recording_origin_matches(s,binding,1));
 (void)auto_batch;struct selection selected={0};
 assert(!choose_visit("20261028000000",1,100,true,&selected)&&!selected.first_count);
 settings.epoch=2;assert(!choose_visit(s,1,100,true,&selected)&&!selected.first_count);settings.epoch=1;
 assert(!choose_visit(s,1,100,true,&selected)&&selected.first_count==1);
 const char*newer="20261028000003";session_dir(newer);assert(!recording_origin_create(newer,other,1));
 assert(!choose_visit(newer,1,100,true,&selected)&&selected.first_count==1);
 newer="20261028000004";session_dir(newer);assert(!recording_origin_create(newer,binding,1));
 assert(!choose_visit(newer,1,100,true,&selected)&&selected.first_count==2&&!strcmp(selected.first[1].session,newer));
 s="20261028000002";session_dir(s);assert(!recording_origin_create(s,"",0));assert(!recording_origin_matches(s,binding,1));assert(recording_origin_create(s,binding,1)==-EEXIST);
 for(unsigned fault=0;fault<4;fault++){
  char id[15];snprintf(id,sizeof(id),"202610280000%02u",10+fault);session_dir(id);
  write_short=fault==0;sync_error=fault==1;close_error=fault==2;rename_error=fault==3;
  assert(recording_origin_create(id,binding,1)==-EIO);write_short=sync_error=close_error=rename_error=0;
  assert(!recording_origin_matches(id,binding,1)); /* No partially published origin. */
 }
 s="20261028000001";char path[256];snprintf(path,sizeof(path),"%s/%s/binding.bin",directory,s);int fd=open(path,O_RDWR);assert(fd>=0);uint8_t b;assert(pread(fd,&b,1,12)==1);b^=1;assert(pwrite(fd,&b,1,12)==1&&!close(fd));assert(!recording_origin_matches(s,binding,1));
 for(unsigned kind=0;kind<4;kind++){
  char id[15],orphan[256];snprintf(id,sizeof(id),"202610280000%02u",20+kind);session_dir(id);
  snprintf(orphan,sizeof(orphan),"%s/%s/%s",directory,id,kind==0?"0/0001.opus":kind==1?"marks.bin":kind==2?"unknown":"0/nested");
  if(kind<2){int audio=open(orphan,O_CREAT|O_WRONLY,0600);assert(audio>=0&&write(audio,"OLD_AUDIO",9)==9&&!close(audio));}
  else {assert(!mkdir(orphan,0700));}
  assert(recording_origin_create(id,binding,1)==-EEXIST&&!recording_origin_matches(id,binding,1));
  if(kind<2){char bytes[10]={0};int audio=open(orphan,O_RDONLY);assert(audio>=0&&read(audio,bytes,9)==9&&!strcmp(bytes,"OLD_AUDIO")&&!close(audio));}
 }
 s="20261028000030";session_dir(s);stat_error=1;
 assert(recording_origin_create(s,binding,1)==-EEXIST);stat_error=0;
 assert(!recording_origin_matches(s,binding,1));
 assert(!locked);return 0;
}
'''


class RecordingOriginTest(unittest.TestCase):
    def test_immutable_origin_unknown_epoch_and_torn_write_all_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = (ROOT/'applications/clip/src/upload_runtime.c').read_text()
            selection = runtime[runtime.index('#define AUTO_BATCH_FILES'):runtime.index('static void select_candidate')]
            adapters = r'''
#define MAX_FILE (8U*1024U*1024U)
#define MIN(a,b) ((a)<(b)?(a):(b))
static struct upload_config settings={.binding_id="0123456789abcdef0123456789abcdef",.epoch=1};
static char cursor_session[15];
static uint32_t cursor_segment;
int upload_state_load(const char*s,uint32_t n,struct upload_file_record*r){(void)s;(void)n;(void)r;return -ENOENT;}
'''
            source = PRELUDE + without_includes(ROOT/'applications/clip/src/recording_origin.c') + adapters + selection + MAIN
            (root/'test.c').write_text(source)
            subprocess.run(['clang','-std=gnu11','-Wall','-Wextra','-Werror',
                            '-fsanitize=address,undefined','-I'+str(ROOT/'applications/clip/include'),
                            str(root/'test.c'),'-o',str(root/'test')],check=True)
            data=root/'data'
            data.mkdir()
            subprocess.run([str(root/'test'),str(data)],check=True)

    def test_real_session_creation_captures_once_before_audio_and_keeps_failed_origins_offline(self):
        from test_baseline_responses import function
        adapters = r'''
#define CONFIG_BOA_USER_BINDING 1
#define STORAGE_SESSION_ID_LEN 32
#define K_FOREVER 0
#define LOG_WRN(...) ((void)0)
#define LOG_INF(...) ((void)0)
#define LOG_ERR(...) ((void)0)
static bool sd_mounted=true,expect_origin;
static unsigned marks_created,json_created;
static char current_session_id[32];
static uint64_t total_bytes,session_bytes_base;
static struct upload_config config={.binding_id="0123456789abcdef0123456789abcdef",.epoch=1};
static struct upload_config *configuration=&config;
#define settings (*configuration)
static int control_lock;
struct k_spinlock {int held;};
typedef int k_spinlock_key_t;
static k_spinlock_key_t k_spin_lock(struct k_spinlock*m){assert(!m->held);m->held=1;return 0;}
static void k_spin_unlock(struct k_spinlock*m,k_spinlock_key_t key){(void)key;assert(m->held);m->held=0;}
static void k_mutex_lock(int*m,int timeout){(void)timeout;assert(!*m);*m=1;}
static void k_mutex_unlock(int*m){assert(*m);*m=0;}
static int validate_session_id(const char*s){return strlen(s)==14?0:-EINVAL;}
static int ensure_bucket_directories(const char*s){char path[256];snprintf(path,sizeof(path),"%s/%s",directory,s);if(mkdir(path,0700)&&errno!=EEXIST)return -errno;strcat(path,"/0");return mkdir(path,0700)&&errno!=EEXIST?-errno:0;}
static int build_session_metadata_path(const char*s,char*p,size_t n){return storage_build_session_metadata_path(s,p,n);}
static int build_marks_path(const char*s,char*p,size_t n){return storage_build_session_metadata_path(s,p,n);}
static int create_marks_file(const char*p){(void)p;marks_created++;return 0;}
static int create_session_json(const char*p,const char*s,uint8_t c,uint32_t rate,const char*mode){
 (void)c;(void)rate;(void)mode;assert(!control_lock);json_created++;
 assert(recording_origin_matches(s,config.binding_id,config.epoch)==expect_origin);
 int fd=open(p,O_CREAT|O_WRONLY,0600);assert(fd>=0&&write(fd,"recording",9)==9&&!close(fd));return 0;
}
'''
        source = PRELUDE + without_includes(ROOT/'applications/clip/src/recording_origin.c') + adapters
        runtime = (ROOT/'applications/clip/src/upload_runtime.c').read_text()
        start = runtime.index('struct recording_origin_snapshot {')
        source += runtime[start:runtime.index('int upload_runtime_factory_reset(', start)]
        source += function((ROOT/'applications/clip/src/storage.c').read_text(),'int storage_create_session(')
        source += r'''
int main(int argc,char**argv){
 assert(argc==2);directory=argv[1];expect_origin=true;
 assert(upload_runtime_recording_origin("20261028000000")==-EAGAIN);
 k_mutex_lock(&control_lock,K_FOREVER);publish_recording_origin();k_mutex_unlock(&control_lock);
 const char*s="20261028000000",*old="0123456789abcdef0123456789abcdef";
 assert(!storage_create_session(s,1,16000,"normal"));
 strcpy(config.binding_id,"1123456789abcdef0123456789abcdef");config.epoch=2;
 k_mutex_lock(&control_lock,K_FOREVER);publish_recording_origin();k_mutex_unlock(&control_lock);
 assert(recording_origin_matches(s,old,1)&&!recording_origin_matches(s,config.binding_id,2));
 expect_origin=false;
 char prior[256],bytes[10]={0};storage_build_session_metadata_path(s,prior,sizeof(prior));int oldfd=open(prior,O_WRONLY);assert(oldfd>=0&&write(oldfd,"OLD_BYTES",9)==9&&!close(oldfd));
 assert(storage_create_session(s,1,16000,"normal")==-EEXIST);assert(marks_created==1&&json_created==1);
 oldfd=open(prior,O_RDONLY);assert(oldfd>=0&&read(oldfd,bytes,9)==9&&!strcmp(bytes,"OLD_BYTES")&&!close(oldfd));
 s="20261028000001";config.binding_id[0]=0;config.epoch=0;publish_recording_origin();assert(!storage_create_session(s,1,16000,"normal"));
 strcpy(config.binding_id,old);config.epoch=1;publish_recording_origin();assert(!recording_origin_matches(s,old,1));
 s="20261028000002";sync_error=1;assert(!storage_create_session(s,1,16000,"normal"));sync_error=0;assert(!recording_origin_matches(s,old,1));
 char p[256];storage_build_session_metadata_path(s,p,sizeof(p));struct stat st;assert(!stat(p,&st)&&st.st_size==9);
 assert(!control_lock&&!locked);return 0;
}
'''
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'test.c').write_text(source)
            subprocess.run(['clang','-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                            '-I'+str(ROOT/'applications/clip/include'),str(root/'test.c'),'-o',str(root/'test')],check=True)
            (root/'data').mkdir()
            subprocess.run([str(root/'test'),str(root/'data')],check=True)

    def test_audio_collision_aborts_before_file_open_and_releases_hardware_and_codecs(self):
        from test_auto_upload import compile_run
        from test_baseline_responses import function
        source = r'''
#define CONFIG_BOA_USER_BINDING 1
#define CONFIG_SPEEXDSP 1
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
static void ignore_log(const char*format,...){(void)format;}
#define LOG_INF(...) ignore_log(__VA_ARGS__)
#define LOG_WRN(...) ((void)0)
#define LOG_DBG(...) ((void)0)
#define LOG_ERR(...) ((void)0)
#define AUDIO_SAMPLE_RATE 16000
#define CONFIG_CLIP_NORMAL_BITRATE 32000
#define CONFIG_CLIP_ENHANCED_BITRATE 24000
#define MODE_ENHANCED 1
#define DMIC_TRIGGER_START 1
#define DMIC_TRIGGER_STOP 2
#define CoreDebug_DEMCR_TRCENA_Msk 1
#define DWT_CTRL_CYCCNTENA_Msk 1
static struct {unsigned DEMCR;} core_debug;
static struct {unsigned CYCCNT,CTRL;} dwt;
#define CoreDebug (&core_debug)
#define DWT (&dwt)
enum audio_mode {AUDIO_MODE_STEREO};
static enum audio_mode current_mode=AUDIO_MODE_STEREO;
struct clip_context {struct {int mode,noise_suppress;}config;};
static struct clip_context ctx;
static struct clip_context*clip_get_context(void){return &ctx;}
static struct {unsigned encode_time_min_us;}stats;
static unsigned encode_time_total_us,dsp_time_total_us,agc_hp_x1,agc_envelope,agc_gain_q8,current_file_index,file_start_frame_count;
static unsigned file_opens;
static int boost,mic,dmic,dmic_dev,opus,dsp_cleanup,collision=-EEXIST;
static bool recording_active,is_paused,speex_enabled;
static void*speex_pp;
static char current_session_id[15]="20261028000000";
static int current_storage_file;
static void audio_wait_haptic_quiet(void){}
static void clip_cpu_boost_acquire(void){assert(!boost);boost=1;}
static void clip_cpu_boost_release(void){assert(boost);boost=0;}
static int mic_power_on(void){mic=1;return 0;}
static int mic_power_off(void){mic=0;return 0;}
static int init_opus_encoder(void){opus=1;return 0;}
void cleanup_opus_encoder(void){opus=0;}
static int init_speex_preprocessor(void){return 0;}
static void cleanup_speex_preprocessor(void){dsp_cleanup++;speex_enabled=false;speex_pp=NULL;}
static int dmic_trigger(int dev,int action){(void)dev;dmic=action==DMIC_TRIGGER_START;return 0;}
static void dmic_flush_initial(void){}
static int storage_create_session(const char*s,uint8_t c,uint32_t rate,const char*mode){assert(s&&c==2&&rate==16000&&mode);return collision;}
static int storage_create_file(int*f,const char*s,unsigned index){(void)f;(void)s;assert(index==1);file_opens++;return 0;}
'''
        source += function((ROOT/'applications/clip/src/audio.c').read_text(),'static int audio_start_recording_internal(enum audio_mode mode)\n{')
        source += r'''
int main(void){
 assert(audio_start_recording_internal(AUDIO_MODE_STEREO)==-EEXIST);
 assert(!file_opens&&!recording_active&&!boost&&!mic&&!dmic&&!opus&&dsp_cleanup==1);
 collision=0;assert(!audio_start_recording_internal(AUDIO_MODE_STEREO));
 assert(file_opens==1&&recording_active&&boost&&mic&&dmic&&opus);return 0;
}
'''
        compile_run(source)
