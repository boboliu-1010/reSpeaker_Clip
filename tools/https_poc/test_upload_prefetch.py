"""Actual producer C with pthread synchronization and adversarial SD adapters."""
from pathlib import Path
import json
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = r'''
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/types.h>
#include "upload_prefetch.h"
#define MIN(a,b) ((a)<(b)?(a):(b))
#define ARG_UNUSED(a) (void)(a)
#define K_FOREVER (-1)
#define K_NO_WAIT 0
#define K_MSEC(a) (a)
#define FS_SEEK_SET 0
#define FS_O_READ 1
typedef atomic_int atomic_t;
typedef unsigned char k_thread_stack_t;
struct k_sem {pthread_mutex_t mutex;pthread_cond_t cond;unsigned count;};
struct k_thread {pthread_t tid;void (*entry)(void*,void*,void*);void *arg;};
struct fs_file_t {size_t pos;bool opened;};
static atomic_int allocations,frees,allocation_calls,fail_allocation;
static atomic_int open_failure,read_failure,close_failure,join_failure,cancelled;
static atomic_int live_files,reading;
static size_t max_read;
static unsigned char content[574179];
static pthread_mutex_t gate=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed=PTHREAD_COND_INITIALIZER;
static bool block_read,entered,release_read;
static int atomic_get(atomic_t *p){return atomic_load(p);}
static void atomic_set(atomic_t *p,int value){atomic_store(p,value);}
static void *k_malloc(size_t n){
 int call=atomic_fetch_add(&allocation_calls,1)+1;
 if(call==atomic_load(&fail_allocation))return NULL;
 void *p=malloc(n);assert(p);atomic_fetch_add(&allocations,1);return p;
}
static void k_free(void *p){if(p){atomic_fetch_add(&frees,1);free(p);}}
static uint64_t k_uptime_ticks(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000+t.tv_nsec/1000;}
static uint64_t k_ticks_to_us_floor64(uint64_t t){return t;}
static void k_sem_init(struct k_sem *s,unsigned n,unsigned max){(void)max;assert(!pthread_mutex_init(&s->mutex,NULL));assert(!pthread_cond_init(&s->cond,NULL));s->count=n;}
static void k_sem_give(struct k_sem *s){pthread_mutex_lock(&s->mutex);s->count=1;pthread_cond_signal(&s->cond);pthread_mutex_unlock(&s->mutex);}
static int k_sem_take(struct k_sem *s,int timeout){
 pthread_mutex_lock(&s->mutex);int ret=0;
 struct timespec end;clock_gettime(CLOCK_REALTIME,&end);
 if(timeout>0){end.tv_nsec+=(long)timeout*1000000;end.tv_sec+=end.tv_nsec/1000000000;end.tv_nsec%=1000000000;}
 while(!s->count){
  if(!timeout){ret=-EAGAIN;break;}
  int e=timeout<0?pthread_cond_wait(&s->cond,&s->mutex):pthread_cond_timedwait(&s->cond,&s->mutex,&end);
  if(e==ETIMEDOUT){ret=-EAGAIN;break;}assert(!e);
 }
 if(!ret)s->count=0;
 pthread_mutex_unlock(&s->mutex);return ret;
}
static k_thread_stack_t *k_thread_stack_alloc(size_t n,int flags){assert(!flags);return k_malloc(n);}
static int k_thread_stack_free(k_thread_stack_t *p){k_free(p);return 0;}
static void *trampoline(void *arg){struct k_thread *t=arg;t->entry(t->arg,NULL,NULL);return NULL;}
static void k_thread_create(struct k_thread *t,k_thread_stack_t *stack,size_t n,
 void (*entry)(void*,void*,void*),void *arg,void *a,void *b,int priority,int options,int delay){
 assert(stack&&n==4096&&!a&&!b&&priority>=6&&priority<=8&&!options&&!delay);t->entry=entry;t->arg=arg;
 assert(!pthread_create(&t->tid,NULL,trampoline,t));
}
static void k_thread_name_set(struct k_thread *t,const char *name){(void)t;assert(!strcmp(name,"upload_sd"));}
static int k_thread_join(struct k_thread *t,int timeout){assert(timeout==K_FOREVER);if(atomic_load(&join_failure))return -EAGAIN;return -pthread_join(t->tid,NULL);}
static int k_thread_stack_space_get(struct k_thread *t,size_t *unused){(void)t;*unused=3072;return 0;}
static void fs_file_t_init(struct fs_file_t *f){memset(f,0,sizeof(*f));}
static int fs_open(struct fs_file_t *f,const char *path,int flags){assert(!strcmp(path,"record.opus")&&flags==FS_O_READ);if(atomic_load(&open_failure))return -EACCES;f->opened=true;atomic_fetch_add(&live_files,1);return 0;}
static int fs_seek(struct fs_file_t *f,uint32_t pos,int whence){assert(f->opened&&whence==FS_SEEK_SET&&pos<=sizeof(content));f->pos=pos;return 0;}
static ssize_t fs_read(struct fs_file_t *f,void *out,size_t length){
 assert(f->opened);atomic_fetch_add(&reading,1);
 pthread_mutex_lock(&gate);
 if(block_read){entered=true;pthread_cond_broadcast(&changed);while(!release_read)pthread_cond_wait(&changed,&gate);block_read=false;}
 pthread_mutex_unlock(&gate);
 int error=atomic_load(&read_failure);
 if(error){atomic_fetch_sub(&reading,1);return error;}
 if(max_read&&length>max_read)length=max_read;
 assert(f->pos+length<=sizeof(content));memcpy(out,content+f->pos,length);f->pos+=length;
 atomic_fetch_sub(&reading,1);return (ssize_t)length;
}
static int fs_close(struct fs_file_t *f){assert(f->opened&&!atomic_load(&reading));f->opened=false;atomic_fetch_sub(&live_files,1);return atomic_load(&close_failure)?-EIO:0;}
static int check(void){return atomic_load(&cancelled)?-ECANCELED:0;}
'''

MAIN = r'''
static void reset(void){
 assert(atomic_load(&allocations)==atomic_load(&frees));assert(!atomic_load(&live_files));
 atomic_store(&allocation_calls,0);atomic_store(&fail_allocation,0);
 atomic_store(&open_failure,0);atomic_store(&read_failure,0);atomic_store(&close_failure,0);
 atomic_store(&join_failure,0);atomic_store(&cancelled,0);max_read=0;
 block_read=entered=release_read=false;
}
static void finish(struct upload_prefetch **p,uint8_t *buffer){
 struct upload_prefetch_stats stats={0};assert(!upload_prefetch_close(p,&stats)&&!*p);
 assert(stats.started&&stats.stack_size==4096&&stats.stack_peak==1024);
 k_free(buffer);reset();
}
static void sequential(unsigned limit){
 reset();max_read=limit;struct upload_prefetch *p=NULL;
 assert(!upload_prefetch_open(&p,"record.opus",sizeof(content),8,check));
 uint8_t *buffer=k_malloc(8192);uint32_t length;
 for(uint32_t off=0;off<sizeof(content);off+=length){
  assert(upload_prefetch_take(p,off,&buffer,&length)==1);
  assert(length==MIN(8192,sizeof(content)-off)&&!memcmp(buffer,content+off,length));
 }
 assert(p->stats.deliveries==(sizeof(content)+8191)/8192);
 finish(&p,buffer);
}
static void random_offsets(void){
 reset();struct upload_prefetch *p=NULL;
 assert(!upload_prefetch_open(&p,"record.opus",sizeof(content),8,check));
 uint8_t *buffer=k_malloc(8192);uint32_t length;
 assert(upload_prefetch_take(p,0,&buffer,&length)==1);
 for(unsigned i=0;i<300;i++){
  uint32_t off=(i*19471u)%sizeof(content);uint8_t *old=buffer;length=123;
  int ret=upload_prefetch_take(p,off,&buffer,&length);
  if(ret==1)assert(length==MIN(8192,sizeof(content)-off)&&!memcmp(buffer,content+off,length));
  else assert(!ret&&buffer==old&&length==123);
 }
 finish(&p,buffer);
}
static void failures(void){
 for(int i=1;i<=3;i++){
  reset();atomic_store(&fail_allocation,i);struct upload_prefetch *p=NULL;
  assert(upload_prefetch_open(&p,"record.opus",sizeof(content),8,check)==-ENOMEM&&!p);
 }
 reset();atomic_store(&open_failure,1);struct upload_prefetch *p=NULL;
 assert(upload_prefetch_open(&p,"record.opus",sizeof(content),8,check)==-EACCES&&!p);
 reset();assert(!upload_prefetch_open(&p,"record.opus",sizeof(content),8,check));
 uint8_t *buffer=k_malloc(8192),*old=buffer;uint32_t length=123;
 atomic_store(&read_failure,-EIO);
 assert(!upload_prefetch_take(p,0,&buffer,&length)&&old==buffer&&length==123);
 assert(p->stats.read_error==-EIO&&p->stats.fallbacks==1);
 assert(!upload_prefetch_take(p,8192,&buffer,&length));finish(&p,buffer);
 reset();assert(!upload_prefetch_open(&p,"record.opus",sizeof(content),8,check));
 buffer=k_malloc(8192);atomic_store(&read_failure,0);
 assert(upload_prefetch_take(NULL,0,&buffer,&length)==-EINVAL);
 assert(upload_prefetch_take(p,sizeof(content),&buffer,&length)==-EINVAL);
 atomic_store(&cancelled,1);assert(upload_prefetch_take(p,0,&buffer,&length)==-ECANCELED);
 finish(&p,buffer);
 reset();assert(!upload_prefetch_open(&p,"record.opus",sizeof(content),8,check));
 buffer=k_malloc(8192);struct upload_prefetch_stats stats;
 atomic_store(&join_failure,1);
 assert(upload_prefetch_close(&p,&stats)==-EAGAIN&&p&&atomic_load(&live_files)==1);
 atomic_store(&join_failure,0);finish(&p,buffer);
 reset();assert(!upload_prefetch_open(&p,"record.opus",sizeof(content),8,check));
 atomic_store(&close_failure,1);
 assert(upload_prefetch_close(&p,&stats)==-EIO&&!p&&stats.close_error==-EIO);reset();
}
static struct upload_prefetch *closing;
static struct upload_prefetch_stats closed_stats;
static atomic_int close_started,close_finished;
static void *closer(void *unused){(void)unused;atomic_store(&close_started,1);assert(!upload_prefetch_close(&closing,&closed_stats));atomic_store(&close_finished,1);return NULL;}
static void blocked_cancel(void){
 reset();assert(!upload_prefetch_open(&closing,"record.opus",sizeof(content),8,check));
 /* Queue a read, wait until it is inside the SD adapter, then cancel. */
 pthread_mutex_lock(&gate);block_read=true;pthread_mutex_unlock(&gate);
 request(closing,0);
 pthread_mutex_lock(&gate);while(!entered)pthread_cond_wait(&changed,&gate);pthread_mutex_unlock(&gate);
 uint8_t *buffer=k_malloc(8192),*old=buffer;uint32_t length=123;
 atomic_store(&cancelled,1);
 assert(upload_prefetch_take(closing,0,&buffer,&length)==-ECANCELED&&buffer==old&&length==123);
 pthread_t thread;assert(!pthread_create(&thread,NULL,closer,NULL));
 while(!atomic_load(&close_started)){}
 /* The producer is still blocked: a close may not free or close its file. */
 assert(!atomic_load(&close_finished)&&atomic_load(&live_files)==1&&atomic_load(&reading)==1);
 pthread_mutex_lock(&gate);release_read=true;pthread_cond_broadcast(&changed);pthread_mutex_unlock(&gate);
 assert(!pthread_join(thread,NULL));assert(!closing&&atomic_load(&close_finished));
 k_free(buffer);reset();
}
int main(void){
 for(size_t i=0;i<sizeof(content);i++)content[i]=(uint8_t)(i*17+3);
 sequential(0);sequential(333);random_offsets();failures();blocked_cancel();
 for(unsigned priority=6;priority<=8;priority++){
  struct upload_prefetch *p=NULL;assert(!upload_prefetch_open(&p,"record.opus",sizeof(content),priority,check));
  uint8_t *buffer=k_malloc(8192);uint32_t length;assert(upload_prefetch_take(p,0,&buffer,&length)==1);
  finish(&p,buffer);
 }
 struct upload_prefetch *invalid=NULL;
 assert(upload_prefetch_open(&invalid,"record.opus",sizeof(content),5,check)==-EINVAL);
 assert(upload_prefetch_open(&invalid,"record.opus",sizeof(content),9,check)==-EINVAL);
 puts("prefetch ownership, real threads, fallback, cancellation and cleanup OK");return 0;
}
'''


class PrefetchTest(unittest.TestCase):
    def test_actual_usb_snapshot_format_and_saturation(self):
        text = (ROOT / 'applications/clip/src/https_poc.c').read_text()
        start = text.index('            if (ctx->args && !strcmp(ctx->args, "prefetch"))')
        branch = text[start:text.index('#endif', start)]
        code = r'''
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include "upload_prefetch.h"
#define MIN(a,b) ((a)<(b)?(a):(b))
static bool datagram_prefetch_enabled=true;
static uint8_t datagram_prefetch_priority=8;
static struct upload_prefetch_stats last_prefetch={.started=true,.read_us=(uint64_t)UINT32_MAX+9,.seek_us=17,.wait_us=42,.requests=7,.reads=8,.deliveries=6,.fallbacks=1,.discarded=2,.stack_size=4096,.stack_peak=1234};
struct ctx {const char *args;};
static int query(struct ctx *ctx,char *response,size_t length){
''' + branch + r'''
 return -1;
}
int main(void){struct ctx ctx={"prefetch"};char response[512];int n=query(&ctx,response,sizeof(response));if(n<=0||n>=512)return 1;puts(response);return 0;}
'''
        self.assertNotIn('%llu', branch)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'test.c').write_text(code)
            subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-I'+str(ROOT/'applications/clip/include'),
                            str(root/'test.c'), '-o', str(root/'test')], check=True)
            output = subprocess.check_output([str(root/'test')], text=True)
        value = json.loads(output)['data']
        self.assertTrue(value['saturated'])
        self.assertEqual(value['read_us'], 0xffffffff)
        self.assertEqual((value['seek_us'], value['wait_us'], value['requests']), (17, 42, 7))
        self.assertEqual(value['stack_peak'], 1234)

    def run_c(self, extra, main):
        source = (ROOT / 'applications/clip/src/upload_prefetch.c').read_text()
        source = '\n'.join(x for x in source.splitlines() if not x.startswith('#include'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'test.c').write_text(FIXTURE + source + extra + main)
            subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-pthread',
                            '-I'+str(ROOT/'applications/clip/include'),
                            str(root/'test.c'), '-o', str(root/'test')], check=True)
            subprocess.run([str(root/'test')], check=True, timeout=20)

    def test_actual_producer_and_ownership(self):
        self.run_c('', MAIN)

    def test_real_datagram_reader_with_swapped_buffers_and_retransmissions(self):
        text = (ROOT / 'applications/clip/src/https_poc.c').read_text()
        reader = 'static int datagram_read' + text.split('static int datagram_read', 1)[1].split('static void datagram_progress', 1)[0]
        extra = r'''
#define CONFIG_CLIP_DTLS_PREFETCH 1
#include "dtls_profile.h"
static struct upload_prefetch *datagram_prefetch;
static struct fs_file_t file;
static uint8_t io[4096],*datagram_cache;
static size_t file_length=sizeof(content);
static uint32_t cache_offset,cache_length;
static uint16_t datagram_cache_bytes=8192;
static int check_cancel(void){return check();}
'''
        main = r'''
int main(void){
 for(size_t i=0;i<sizeof(content);i++)content[i]=(uint8_t)(i*17+3);
 for(unsigned trial=0;trial<3;trial++){
  max_read=trial==1?333:0;
  fs_file_t_init(&file);assert(!fs_open(&file,"record.opus",FS_O_READ));
  datagram_cache=k_malloc(8192);cache_length=0;
  assert(!upload_prefetch_open(&datagram_prefetch,"record.opus",sizeof(content),8,check));
  uint8_t out[1024];
  for(uint32_t off=0;off<file_length;off+=sizeof(out)){
   size_t length=MIN(sizeof(out),file_length-off);
   assert(!datagram_read(off,out,length)&&!memcmp(out,content+off,length));
   if(trial==2&&off>16384&&(off%16384)==0){
    assert(!datagram_read(off-16384,out,sizeof(out))&&!memcmp(out,content+off-16384,sizeof(out)));
   }
  }
  assert(!datagram_read(file_length-739,out,739)&&!memcmp(out,content+file_length-739,739));
  atomic_store(&cancelled,1);assert(datagram_read(0,out,sizeof(out))==-ECANCELED);atomic_store(&cancelled,0);
  struct upload_prefetch_stats stats;
  assert(!upload_prefetch_close(&datagram_prefetch,&stats));
  assert(!fs_close(&file));k_free(datagram_cache);datagram_cache=NULL;
  assert(!atomic_load(&live_files)&&atomic_load(&allocations)==atomic_load(&frees));
 }
 puts("real datagram reader and asynchronous swap/retransmission integration OK");
 return 0;
}
'''
        self.run_c(extra + reader, main)


if __name__ == '__main__':
    unittest.main()
