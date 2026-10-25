"""Run actual BLE event queue/formatting with deterministic clock and transport."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_auto_upload import without_includes
from test_auto_upload import compile_run

ROOT = Path(__file__).resolve().parents[2]


class UploadAppEventsTest(unittest.TestCase):
    def test_ble_message_keeps_reference_across_disconnect_and_releases_on_errors(self):
        source = (ROOT/'applications/clip/src/ble.c').read_text()
        send = source[source.index('static int ble_send_message'):source.index('int ble_notify_state_change')]
        code = r'''
#define CONFIG_CLIP_UPLOAD_APP 1
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <errno.h>
#define K_FOREVER 0
#define BT_SECURITY_L2 2
typedef int k_spinlock_key_t;
struct bt_conn {int refs,security;};
static struct bt_conn original={.refs=1,.security=2},replacement={.refs=1,.security=2};
static struct {struct bt_conn*conn;bool notify_enabled;} ble_ctx={&original,true};
static struct {int attrs[8];} clip_svc;
static int response_conn_lock,response_send_lock,calls,mode;
static int k_spin_lock(int*m){assert(!*m);*m=1;return 0;}
static void k_spin_unlock(int*m,int key){(void)key;assert(*m);*m=0;}
static void k_mutex_lock(int*m,int wait){(void)wait;assert(!*m);*m=1;}
static void k_mutex_unlock(int*m){assert(*m);*m=0;}
static struct bt_conn*bt_conn_ref(struct bt_conn*c){assert(c&&c->refs>0);c->refs++;return c;}
static void bt_conn_unref(struct bt_conn*c){assert(c&&c->refs>0);c->refs--;}
static int bt_conn_get_security(struct bt_conn*c){assert(c->refs>0);return c->security;}
static int bt_gatt_get_mtu(struct bt_conn*c){assert(c->refs>0);return 23;}
static int bt_gatt_notify(struct bt_conn*c,const void*attr,const void*data,uint16_t n){
 assert(c==&original&&c->refs>0&&attr==&clip_svc.attrs[4]&&data&&n<=20&&!response_conn_lock&&response_send_lock);calls++;
 if(mode==1&&calls==1){int key=k_spin_lock(&response_conn_lock);ble_ctx.conn=&replacement;k_spin_unlock(&response_conn_lock,key);bt_conn_unref(&original);}
 return mode==2&&calls==2?-EIO:0;
}
static void ble_activity_refresh(void){}
static void k_yield(void){}
static void ignore_log(const char*format,...){(void)format;}
#define LOG_ERR(...) ignore_log(__VA_ARGS__)
#define LOG_DBG(...) ignore_log(__VA_ARGS__)
'''
        code += send
        code += r'''
int main(int argc,char**argv){
 assert(argc==2);mode=atoi(argv[1]);uint8_t body[60]={0};
 if(mode==3)original.security=1;
 if(mode==4)ble_ctx.conn=NULL;
 int ret=ble_send(body,sizeof(body));
 assert(!response_conn_lock&&!response_send_lock);
 if(mode==0)assert(!ret&&calls==3&&original.refs==1);
 if(mode==1)assert(!ret&&calls==3&&!original.refs&&replacement.refs==1);
 if(mode==2)assert(ret==-EIO&&calls==2&&original.refs==1);
 if(mode==3)assert(ret==-EACCES&&!calls&&original.refs==1);
 if(mode==4)assert(ret==-ENOTCONN&&!calls&&original.refs==1);
 return 0;
}
'''
        for mode in range(5):
            with self.subTest(mode=mode):
                compile_run(code, [str(mode)])

    def test_throttle_completed_file_snapshot_overflow_retry_and_reconnect(self):
        code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include "upload_app.h"
#define K_NO_WAIT 0
typedef int atomic_t;
#define ATOMIC_INIT(x) (x)
static int atomic_inc(int *p){return (*p)++;}
static int atomic_get(int *p){return *p;}
static void atomic_set(int *p,int n){*p=n;}
static bool atomic_cas(int *p,int old,int n){if(*p!=old)return false;*p=n;return true;}
struct queue {unsigned char bytes[8][256];size_t size;unsigned head,count;};
#define K_MSGQ_DEFINE(name,item,count,align) static struct queue name={.size=(item)}
static int k_msgq_put(struct queue*q,const void*p,int wait){assert(wait==0&&q->size<=256);if(q->count==8)return -ENOMSG;memcpy(q->bytes[(q->head+q->count++)%8],p,q->size);return 0;}
static int k_msgq_get(struct queue*q,void*p,int wait){assert(!wait);if(!q->count)return -ENOMSG;memcpy(p,q->bytes[q->head],q->size);q->head=(q->head+1)%8;q->count--;return 0;}
static void k_msgq_purge(struct queue*q){q->count=q->head=0;}
static int64_t now;
static int connected,notify,send_failure,sends;
static char messages[64][512];
static struct upload_app_status status={.stage="idle"};
static struct upload_app_network network={.state="idle"};
static int64_t k_uptime_get(void){return now;}
static bool ble_is_connected(void){return connected;}
static bool ble_is_notify_enabled(void){return notify;}
static int ble_send(const uint8_t*p,uint16_t n){if(send_failure)return -EAGAIN;assert(n<512&&sends<64);memcpy(messages[sends],p,n);messages[sends++][n]=0;return 0;}
void https_poc_app_status(struct upload_app_status*out){*out=status;}
void https_poc_app_network(struct upload_app_network*out){*out=network;}
'''
        code += without_includes(ROOT/'applications/clip/src/upload_app.c')
        code += r'''
int main(void){
 upload_app_publish("file_complete");now=250;upload_app_poll();assert(!sends&&!app_events.count);
 connected=notify=1;now=500;upload_app_poll();assert(sends==2&&strstr(messages[0],"wifi_check")&&strstr(messages[1],"snapshot"));
 now=750;upload_app_poll();assert(sends==2);
 status.active=true;status.stage="sending";status.size=1000;status.sent=200;status.segment=1;strcpy(status.session,"20261024054528");
 now=1000;upload_app_poll();assert(sends==3);
 status.sent=400;now=1250;upload_app_poll();assert(sends==3);
 status.sent=600;now=2000;upload_app_poll();assert(sends==4);
 status.confirmed=1000;upload_app_publish("file_complete");status.segment=2;status.confirmed=0;
 now=2250;upload_app_poll();assert(sends==5&&strstr(messages[4],"\"segment\":1,")&&strstr(messages[4],"\"confirmed\":1000,"));
 for(int i=0;i<12;i++){status.segment=100+i;upload_app_publish("file_complete");}
 assert(atomic_get(&lost)==4&&app_events.count==8);
 now=2500;upload_app_poll();assert(sends==6&&strstr(messages[5],"\"segment\":104,")&&strstr(messages[5],"\"lost\":4,"));
 send_failure=1;now=2750;upload_app_poll();assert(sends==6&&pending_valid);
 send_failure=0;now=3000;upload_app_poll();assert(sends==7&&strstr(messages[6],"\"segment\":105,"));
 connected=0;now=3250;upload_app_poll();assert(!app_events.count&&!pending_valid);
 connected=1;upload_app_resync();status.segment=999;now=3500;upload_app_poll();assert(sends==9&&strstr(messages[8],"\"segment\":999,"));
 char small[20],query[448];assert(upload_app_format_status(&status,NULL,0,0,small,sizeof(small))==-ENOSPC);
 assert(upload_app_format_status(&status,NULL,0,0,query,sizeof(query))>0&&!strstr(query,"\"event\""));puts(query);
 status.job=status.segment=status.sent=status.received=status.confirmed=status.size=UINT32_MAX;status.error=INT32_MIN;
 assert(upload_app_format_status(&status,"file_cancelled",UINT32_MAX,UINT32_MAX,query,sizeof(query))>0);puts(query);
 network.state="succeeded";strcpy(network.ip,"192.168.2.180");network.checked_ms=100;
 upload_app_publish_network(&network);now=3750;upload_app_poll();assert(sends==10&&strstr(messages[9],"wifi_dhcp")&&strstr(messages[9],"192.168.2.180"));
 for(int i=0;i<sends;i++)puts(messages[i]);return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'test.c').write_text(code)
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror',
                            '-fsanitize=address,undefined','-I'+str(ROOT/'applications/clip/include'),
                            str(root/'test.c'),'-o',str(root/'test')],check=True)
            result = subprocess.run([str(root/'test')],check=True,capture_output=True,text=True)
            messages = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            self.assertTrue(messages[0]['ok'])
            self.assertEqual(messages[-1]['state'], 'succeeded')
            self.assertTrue(all('password' not in str(m) and 'token' not in str(m) for m in messages))
