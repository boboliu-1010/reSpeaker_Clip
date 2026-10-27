"""Exercise actual DFU callbacks and the shared admission gate without hardware."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


class OtaAdmissionTest(unittest.TestCase):
    def test_dfu_lifecycle_and_conflicting_operations(self):
        source = (ROOT / 'applications/clip/src/clip_event.c').read_text()
        helper = source.split('static bool upload_ota_event', 1)[1].split('\n#endif', 1)[0]
        callback = source.split('static enum mgmt_cb_return mcumgr_dfu_cb(', 1)[1].split(
            '\nstatic struct mgmt_callback mcumgr_dfu_cb_started;', 1)[0]
        policy = (ROOT / 'applications/clip/src/upload_command.c').read_text()
        policy = '\n'.join(x for x in policy.splitlines() if not x.startswith('#include'))
        code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define CONFIG_CLIP_UPLOAD 1
#define LOG_INF(...) ((void)0)
#define LOG_WRN(...) ((void)0)
#define LOG_DBG(...) ((void)0)
#define K_FOREVER 0
#define K_MSEC(x) (x)
#define OTA_PROGRESS_POLL_INTERVAL_MS 200
#define MGMT_ERR_EBUSY 10
#define AT_CMD_TYPE_READ 3
#define AT_CMD_TYPE_TEST 0
#define AT_CMD_TYPE_SET 1
#define AT_CMD_TYPE_EXEC 2
enum clip_state {CLIP_STATE_IDLE, CLIP_STATE_OTA, CLIP_STATE_RECORDING};
enum clip_event {CLIP_EVENT_OTA_START, CLIP_EVENT_OTA_DONE, CLIP_EVENT_STATUS_SHOW,
 CLIP_EVENT_START, CLIP_EVENT_UPLOAD_BEGIN, CLIP_EVENT_POWER_OFF_EXEC};
enum clip_event_result {CLIP_EVENT_OK, CLIP_EVENT_BUSY};
struct clip_event_result_info {enum clip_event_result result; int error_code;};
enum mgmt_cb_return {MGMT_CB_OK, MGMT_CB_ERROR_RC};
enum {MGMT_EVT_OP_IMG_MGMT_DFU_STARTED, MGMT_EVT_OP_IMG_MGMT_DFU_CHUNK,
 MGMT_EVT_OP_IMG_MGMT_DFU_PENDING, MGMT_EVT_OP_IMG_MGMT_DFU_STOPPED};
struct request {size_t off, size;};
struct action {unsigned long long size;};
struct img_mgmt_upload_check {struct request *req; struct action *action;};
static int g_state, ota_mutex, ota_progress_work, posts, sleeps, queue_failures;
static unsigned g_ota_chunk_count;
static size_t g_ota_total_size;
static bool ota_in_progress, recording, downloading, uploading, pending, connected=true;
static bool disconnect_after_admit;
enum {UI_EVENT_OTA_START, UI_EVENT_OTA_DONE};
static int atomic_get(int *v) {return *v;}
static void atomic_set(int *v, int n) {*v=n;}
typedef int atomic_t;
static bool atomic_cas(int *v,int old,int n) {if(*v!=old)return false;*v=n;return true;}
static bool audio_is_recording(void){return recording;}
static bool transfer_is_active(void){return downloading;}
static bool upload_runtime_active(void){return uploading;}
static bool upload_runtime_record_pending(void){return pending;}
static bool ble_is_connected(void){return connected;}
static void display_post_event(int e){(void)e;posts++;}
static int clip_event_get_state(void){return g_state;}
static void k_mutex_lock(int *p,int timeout){(void)p;(void)timeout;}
static void k_mutex_unlock(int *p){(void)p;}
static void k_work_schedule(int *p,int delay){(void)p;(void)delay;}
static void k_work_cancel_delayable(int *p){(void)p;}
static void display_set_ota_progress(unsigned pct){(void)pct;}
static void k_sleep(int delay){(void)delay;sleeps++;}
static int clip_post_event_sync(enum clip_event event, struct clip_event_result_info *result);
'''
        code += policy + '\nstatic bool upload_ota_event' + helper
        code += r'''
static int clip_post_event_sync(enum clip_event event, struct clip_event_result_info *result) {
 if(queue_failures){queue_failures--;return -EAGAIN;}
 assert(upload_ota_event(event,g_state,result));
 if(event==CLIP_EVENT_OTA_START && disconnect_after_admit){
   connected=false;disconnect_after_admit=false;
 }
 return 0;
}
'''
        code += '\nstatic enum mgmt_cb_return mcumgr_dfu_cb(' + callback
        code += r'''
static int feed(unsigned event, void *data, size_t len) {
 int32_t rc=0; uint16_t group=1; bool abort=false;
 int r=mcumgr_dfu_cb(event,MGMT_CB_OK,&rc,&group,&abort,data,len);
 return r==MGMT_CB_OK?0:rc;
}
int main(void) {
 struct clip_event_result_info result;
 /* A disconnect overtaking queued admission must not leave an OTA owner. */
 connected=false;
 assert(feed(MGMT_EVT_OP_IMG_MGMT_DFU_CHUNK,NULL,0)==10);
 assert(g_state==CLIP_STATE_IDLE && admission==AVAILABLE);
 clip_event_ota_cancel();
 connected=true;
 disconnect_after_admit=true;
 assert(feed(MGMT_EVT_OP_IMG_MGMT_DFU_CHUNK,NULL,0)==10);
 assert(g_state==CLIP_STATE_IDLE && admission==AVAILABLE);
 connected=true;
 /* Busy attempts never acquire OTA ownership, including a resumed chunk. */
 g_state=CLIP_STATE_RECORDING;
 assert(feed(MGMT_EVT_OP_IMG_MGMT_DFU_STARTED,NULL,0)==10);
 g_state=CLIP_STATE_IDLE;
 uploading=true;
 assert(feed(MGMT_EVT_OP_IMG_MGMT_DFU_CHUNK,NULL,0)==10);
 uploading=false; pending=true;
 assert(feed(MGMT_EVT_OP_IMG_MGMT_DFU_STARTED,NULL,0)==10); pending=false;
 downloading=true;
 assert(feed(MGMT_EVT_OP_IMG_MGMT_DFU_STARTED,NULL,0)==10); downloading=false;
 assert(upload_command_begin("FORMAT",AT_CMD_TYPE_EXEC,true,false,false,false)==0);
 assert(feed(MGMT_EVT_OP_IMG_MGMT_DFU_STARTED,NULL,0)==10);
 upload_command_end();
 queue_failures=1;
 assert(feed(MGMT_EVT_OP_IMG_MGMT_DFU_STARTED,NULL,0)==10);
 assert(g_state==CLIP_STATE_IDLE && admission==AVAILABLE);
 assert(feed(MGMT_EVT_OP_IMG_MGMT_DFU_STARTED,NULL,0)==0);
 assert(g_state==CLIP_STATE_OTA && admission==OTA && ota_in_progress);
 assert(!upload_command_claim_upload());
 assert(upload_command_begin("START",AT_CMD_TYPE_EXEC,false,false,false,false)==-EBUSY);
 assert(upload_command_begin("FORMAT",AT_CMD_TYPE_EXEC,false,false,false,false)==-EBUSY);
 assert(upload_command_begin("VERSION",AT_CMD_TYPE_READ,false,false,false,false)==0);
 assert(upload_ota_event(CLIP_EVENT_START,g_state,&result)&&result.result==CLIP_EVENT_BUSY);
 assert(upload_ota_event(CLIP_EVENT_UPLOAD_BEGIN,g_state,&result)&&result.result==CLIP_EVENT_BUSY);
 assert(upload_ota_event(CLIP_EVENT_POWER_OFF_EXEC,g_state,&result)&&result.result==CLIP_EVENT_BUSY);
 assert(!upload_ota_event(CLIP_EVENT_STATUS_SHOW,g_state,&result));
 struct request req={.off=1024,.size=4096};struct action action={.size=4096};
 struct img_mgmt_upload_check check={&req,&action};
 assert(feed(MGMT_EVT_OP_IMG_MGMT_DFU_CHUNK,&check,sizeof(check))==0);
 assert(feed(MGMT_EVT_OP_IMG_MGMT_DFU_PENDING,NULL,0)==0);
 assert(!ota_in_progress && g_state==CLIP_STATE_OTA && !upload_command_claim_upload());
 queue_failures=1;clip_event_ota_cancel();
 assert(sleeps==1 && g_state==CLIP_STATE_IDLE && admission==AVAILABLE);
 /* Resume without STARTED must reserve before accepting a chunk. */
 assert(feed(MGMT_EVT_OP_IMG_MGMT_DFU_CHUNK,&check,sizeof(check))==0);
 assert(g_state==CLIP_STATE_OTA && ota_in_progress);
 assert(feed(MGMT_EVT_OP_IMG_MGMT_DFU_STOPPED,NULL,0)==0);
 assert(g_state==CLIP_STATE_IDLE && admission==AVAILABLE && !ota_in_progress);
 assert(upload_command_claim_upload());upload_command_release_upload();
 /* Earlier callback rejection is preserved without acquiring ownership. */
 int32_t rc=42;uint16_t group=1;bool abort=false;
 assert(mcumgr_dfu_cb(MGMT_EVT_OP_IMG_MGMT_DFU_STARTED,MGMT_CB_ERROR_RC,
 &rc,&group,&abort,NULL,0)==MGMT_CB_ERROR_RC && rc==42 && admission==AVAILABLE);
 puts("OTA admission and lifecycle passed");
}
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'test.c').write_text(code)
            subprocess.run(['clang', '-std=c11', '-fsanitize=address,undefined',
                            str(path / 'test.c'), '-o', str(path / 'test')], check=True,
                           capture_output=True, text=True)
            result = subprocess.run([str(path / 'test')], check=True, capture_output=True, text=True)
            self.assertIn('OTA admission and lifecycle passed', result.stdout)
