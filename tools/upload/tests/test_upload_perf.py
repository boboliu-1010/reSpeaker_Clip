"""Exercise the firmware phase-timing ring, without legacy HTTP profiling."""
import errno
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


class UploadPerfTest(unittest.TestCase):
    def test_real_c_ring_cursor_overwrite_busy_oom_and_disable(self):
        source = (ROOT / 'applications/clip/src/upload_perf.c').read_text()
        source = '\n'.join(line for line in source.splitlines() if not line.startswith('#include'))
        fixture = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>
#include "upload_perf.h"
struct k_spinlock {int unused;};
typedef int k_spinlock_key_t;
static int k_spin_lock(struct k_spinlock *p){(void)p;return 0;}
static void k_spin_unlock(struct k_spinlock *p,int key){(void)p;(void)key;}
static uint64_t clock_us;
static uint64_t k_uptime_ticks(void){return clock_us;}
static uint64_t k_ticks_to_us_floor64(uint64_t value){return value;}
static bool fail_alloc;
static void *k_calloc(size_t n,size_t s){return fail_alloc?NULL:calloc(n,s);}
static void k_free(void *p){free(p);}
static int limited_snprintf(char *out,size_t size,const char *format,...){
 assert(!strstr(format,"llu")&&!strstr(format,"lld"));
 va_list args;va_start(args,format);int result=vsnprintf(out,size,format,args);va_end(args);return result;
}
#define snprintf limited_snprintf
'''
        fixture += source
        fixture += r'''
int main(void){
 char out[2048];
 assert(upload_perf_command("on",false,out,sizeof(out))>0);puts(out);
 assert(upload_perf_command("off",true,out,sizeof(out))==-EBUSY);
 assert(upload_perf_command("on",true,out,sizeof(out))==-EBUSY);
 assert(upload_perf_command("",false,out,sizeof(out))==-EINVAL);
 assert(upload_perf_command("-1",false,out,sizeof(out))==-EINVAL);
 assert(upload_perf_command("4294967296",false,out,sizeof(out))==-EINVAL);
 clock_us=100;upload_perf_begin(UP_PUT,"20261021000001",3,16384,16384);
 upload_perf_add(UP_WAIT_WRITE_US,75);upload_perf_add(UP_WANT_WRITE,2);
 assert(upload_perf_command("0",true,out,sizeof(out))>0);puts(out);
 clock_us=300;upload_perf_end(-ECANCELED);
 assert(upload_perf_command("0",true,out,sizeof(out))>0);puts(out);
 assert(upload_perf_command("0",true,out,8)==-ENOSPC);
 for(int i=0;i<20;i++){upload_perf_begin(UP_GET,NULL,0,i,0);clock_us+=10;upload_perf_end(0);}
 assert(upload_perf_command("0",true,out,sizeof(out))>0);puts(out);
 assert(upload_perf_command("21",true,out,sizeof(out))>0);puts(out);
 fail_alloc=true;assert(upload_perf_command("on",false,out,sizeof(out))==-ENOMEM);
 assert(upload_perf_command("21",false,out,sizeof(out))>0);puts(out);
 assert(upload_perf_command("off",false,out,sizeof(out))>0);
 upload_perf_begin(UP_GET,NULL,0,0,0);upload_perf_add(UP_READ_US,10);upload_perf_end(0);
 assert(upload_perf_command("0",true,out,sizeof(out))>0);puts(out);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'test.c').write_text(fixture)
            subprocess.run(['clang', '-std=gnu11', '-DCONFIG_CLIP_UPLOAD_PROFILE=1',
                            '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                            '-I' + str(ROOT / 'applications/clip/include'), str(root / 'test.c'),
                            '-o', str(root / 'test')], check=True)
            output = subprocess.check_output([str(root / 'test')], text=True)
        records = [json.loads(line)['data'] for line in output.splitlines() if line]
        self.assertTrue(records[0]['enabled'])
        self.assertIsNone(records[1]['event'])
        event = records[2]['event']
        self.assertEqual((event['session'], event['segment'], event['offset']), ('20261021000001', 3, 16384))
        self.assertEqual(event['result'], -errno.ECANCELED)
        self.assertEqual(event['elapsed_us'], 200)
        self.assertEqual(event['started_us'], 100)
        self.assertEqual(event['values'][7], 75)
        self.assertEqual(event['values'][11], 2)
        self.assertTrue(records[3]['lost'])
        self.assertEqual(records[3]['event']['seq'], 6)
        self.assertEqual(records[4]['latest'], 21)
        self.assertIsNone(records[4]['event'])
        self.assertEqual(records[5]['latest'], 21)
        self.assertFalse(records[6]['enabled'])
