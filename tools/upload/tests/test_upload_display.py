"""Compile the actual OLED progress rendering and read-only upload snapshot."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


def function(source, signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


class UploadDisplayTest(unittest.TestCase):
    def test_framebuffer_progress_priority_timeout_and_no_app_build(self):
        display = (ROOT/'applications/clip/src/display.c').read_text()
        runtime = (ROOT/'applications/clip/src/upload_runtime.c').read_text()
        getter = function(runtime, 'int upload_runtime_display_percent(void)')
        font_start = display.index('static const uint8_t font_6x12[95][12]')
        font = display[font_start:display.index('\n};',font_start)+3]
        status_start = display.index('\tcase UI_STATE_STATUS_BAR: /* Status bar */')
        status = display[status_start:display.index('\n\tcase UI_STATE_REC_WAVE:',status_start)]
        ota_start = display.index('\tcase UI_STATE_OTA_PROGRESS: /* OTA progress */')
        ota = display[ota_start:display.index('\n\tcase UI_STATE_ERROR:',ota_start)]
        code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>
#define OLED_WIDTH 88
#define OLED_HEIGHT 48
#define ICON_WIDTH 24
#define ICON_HEIGHT 24
#define DISPLAY_STATUS_TIMEOUT_MS 3000
#define DISPLAY_PAIRING_GUIDE_TIMEOUT_MS 10000
#define CONFIG_CLIP_UPLOAD 1
#define K_MSEC(x) (x)
#define snprintk snprintf
typedef int atomic_t;
static int atomic_get(int *p){return *p;}
static int active, initialized, cancelled, display_files_total, display_files_done, stage;
enum {IDLE,PREPARING,CONNECTING,TLS,SENDING,VERIFYING,SUCCEEDED,FAILED,CANCELLED};
#ifdef CONFIG_CLIP_UPLOAD_APP
static int app_lock, app_job_network, locked;
typedef int k_spinlock_key_t;
static int k_spin_lock(int *p){(void)p;assert(!locked);locked=1;return 0;}
static void k_spin_unlock(int *p,int k){(void)p;(void)k;assert(locked);locked=0;}
#endif
static int snapshot_reads;
#define upload_runtime_display_percent upload_runtime_display_percent_impl
'''
        code += getter + r'''
#undef upload_runtime_display_percent
static int upload_runtime_display_percent(void){snapshot_reads++;return upload_runtime_display_percent_impl();}
static struct {uint8_t before;uint8_t pixels[528];uint8_t after;} frame={.before=0xa5,.after=0x5a};
#define display_buffer frame.pixels
typedef int icon_id_t;
enum {ICON_NONE,ICON_OTA};
enum {UI_STATE_OFF,UI_STATE_STATUS_BAR,UI_STATE_REC_WAVE,UI_STATE_PAIRING_GUIDE,UI_STATE_OTA_PROGRESS};
static int g_ui_state,display_timeout_work;
static bool g_recording,g_ota_active,g_upload_visible;
static uint8_t g_ota_percent;
static int64_t g_status_bar_start_ms,now;
static unsigned icons,flushes,status_renders;
static bool bonded=true;
static void clear_screen(uint8_t *buf){memset(buf,0,528);}
static const uint8_t *icon_get_bitmap(icon_id_t icon,void *a,void *b){(void)icon;(void)a;(void)b;icons++;return NULL;}
static void icon_draw_bitmap(uint8_t*b,int x,int y,const uint8_t*i,int w,int h){(void)b;(void)x;(void)y;(void)i;(void)w;(void)h;}
static bool ble_is_bonded(void){return bonded;}
static int64_t k_uptime_get(void){return now;}
static void set_ui_state(int state){if(g_ui_state!=state)g_upload_visible=false;g_ui_state=state;}
static void k_work_schedule(int*p,int delay){(void)p;(void)delay;}
static int timeout_cancels,timeout_restarts;
static void k_work_reschedule(int*p,int delay){(void)p;assert(delay==3000);timeout_restarts++;}
static void k_work_cancel_delayable(int*p){(void)p;timeout_cancels++;}
static void flush_display(void){flushes++;}
static void render_status_bar(uint8_t *buf){clear_screen(buf);status_renders++;}
'''
        code += function(display, 'static inline void set_pixel_direct(') + '\n' + font + '\n'
        code += function(display, 'static void draw_char_6x12(uint8_t *buf, char c, int x, int y)\n{') + '\n'
        code += function(display, 'static int draw_string_6x12(uint8_t *buf, const char *str, int x, int y)\n{') + '\n'
        code += function(display, 'static void render_progress(') + '\n'
        code += function(display, 'static void show_upload_progress(void)') + '\n'
        timeout_start = display.index('\t\tif (g_ui_state == UI_STATE_STATUS_BAR &&\n')
        timeout_end = display.index('\n\t\tif (g_ui_state == UI_STATE_STATUS_BAR ||', timeout_start)
        code += 'static void stale_timeout(void){switch(0){case 0:\n' + display[timeout_start:timeout_end] + '\nbreak;}}\n'
        code += 'static void render_current_state(void){switch(g_ui_state){case UI_STATE_OFF:break;\n' + status + ota + 'default:break;}}\n'
        code += r'''
static int bar_pixels(void){int n=0;for(int x=11;x<=76;x++)n+=(display_buffer[(27/8)*88+x]>>(27%8))&1;return n;}
static void save_frame(const char *name){
 FILE*f=fopen(name,"wb");assert(f);fprintf(f,"P4\n88 48\n");
 for(int y=0;y<48;y++)for(int block=0;block<11;block++){
  uint8_t out=0;for(int bit=0;bit<8;bit++){
   int x=block*8+bit;out|=((display_buffer[(y/8)*88+x]>>(y%8))&1)<<(7-bit);
  }fputc(out,f);
 }fclose(f);
}
int main(void){
 assert(upload_runtime_display_percent()==-1);
 initialized=1;active=1;stage=PREPARING;assert(upload_runtime_display_percent()==-1);
 display_files_total=13;assert(upload_runtime_display_percent()==0);
 stage=SENDING;display_files_done=1;assert(upload_runtime_display_percent()==7);
 display_files_done=6;assert(upload_runtime_display_percent()==46);
 /* Changing files/preparing must preserve whole-job progress. */
 stage=PREPARING;assert(upload_runtime_display_percent()==46);stage=SENDING;
 display_files_total=100;display_files_done=42;assert(upload_runtime_display_percent()==42);
#ifdef CONFIG_CLIP_UPLOAD_APP
 app_job_network=1;assert(upload_runtime_display_percent()==-1);app_job_network=0;
#endif
 g_ui_state=UI_STATE_STATUS_BAR;render_current_state();
 assert(!status_renders&&!icons&&bar_pixels()==27&&g_ui_state==UI_STATE_STATUS_BAR);
 assert(strlen("Uploading...")*6==72 && (88-72)/2+72<=88);
 save_frame("upload-42.pbm");
 display_files_done=0;render_current_state();assert(bar_pixels()==0);
 display_files_done=100;assert(upload_runtime_display_percent()==99);
 stage=SUCCEEDED;render_current_state();assert(bar_pixels()==66);
 display_files_done=UINT32_MAX;assert(upload_runtime_display_percent()==100);
 stage=SENDING;display_files_done=42;
 cancelled=1;assert(upload_runtime_display_percent()==-1);cancelled=0;
 stage=FAILED;assert(upload_runtime_display_percent()==-1);stage=SENDING;
 /* OFF never samples or wakes. Recording/OTA retain their foreground. */
 g_ui_state=UI_STATE_OFF;int reads=snapshot_reads;render_current_state();assert(snapshot_reads==reads);
 g_ui_state=UI_STATE_STATUS_BAR;g_recording=true;render_current_state();assert(status_renders==1&&snapshot_reads==reads);g_recording=false;
 g_ota_active=true;render_current_state();assert(status_renders==2&&snapshot_reads==reads);
 g_ui_state=UI_STATE_OTA_PROGRESS;g_ota_percent=42;render_current_state();
 assert(icons==1&&bar_pixels()==27&&snapshot_reads==reads);save_frame("ota-42.pbm");
 g_ota_active=false;g_ui_state=UI_STATE_STATUS_BAR;now=3000;render_current_state();
 assert(g_ui_state==UI_STATE_STATUS_BAR&&g_upload_visible);
 /* Start wakes even when unbonded and stays lit well beyond three seconds. */
 set_ui_state(UI_STATE_OFF);bonded=false;now=4000;show_upload_progress();
 assert(g_ui_state==UI_STATE_STATUS_BAR&&g_upload_visible&&g_status_bar_start_ms==4000&&timeout_cancels==1);
 now=600000;stale_timeout();render_current_state();assert(g_ui_state==UI_STATE_STATUS_BAR);
 /* Every terminal outcome restores status and starts a fresh timeout. */
 for(int outcome=0;outcome<3;outcome++){
  bonded=true;active=1;stage=SENDING;cancelled=0;show_upload_progress();render_current_state();
  if(outcome==0)active=0;else if(outcome==1)stage=FAILED;else cancelled=1;
  now+=10000;render_current_state();
  assert(g_ui_state==UI_STATE_STATUS_BAR&&!g_upload_visible&&g_status_bar_start_ms==now);
  int64_t ended_at=now;now+=2999;stale_timeout();render_current_state();assert(g_ui_state==UI_STATE_STATUS_BAR);
  now=ended_at+3000;render_current_state();assert(g_ui_state==UI_STATE_OFF);
 }
 assert(timeout_restarts>=3);active=1;stage=SENDING;cancelled=0;
 /* Recording, OTA, other foreground states and stale jobs must never wake. */
 g_ui_state=UI_STATE_OFF;g_recording=true;show_upload_progress();assert(g_ui_state==UI_STATE_OFF);g_recording=false;
 g_ota_active=true;show_upload_progress();assert(g_ui_state==UI_STATE_OFF);g_ota_active=false;
 g_ui_state=UI_STATE_REC_WAVE;show_upload_progress();assert(g_ui_state==UI_STATE_REC_WAVE);
 g_ui_state=UI_STATE_OFF;cancelled=1;show_upload_progress();assert(g_ui_state==UI_STATE_OFF);cancelled=0;
 display_files_total=0;show_upload_progress();assert(g_ui_state==UI_STATE_OFF);display_files_total=100;
 active=0;assert(upload_runtime_display_percent()==-1);
 assert(frame.before==0xa5&&frame.after==0x5a);
}
'''
        for app in (False, True):
            with self.subTest(app=app), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root/'test.c').write_text(('#define CONFIG_CLIP_UPLOAD_APP 1\n' if app else '')+code)
                compiled = subprocess.run(['clang','-std=c11','-fsanitize=address,undefined',
                    str(root/'test.c'),'-o',str(root/'test')],capture_output=True,text=True)
                self.assertEqual(compiled.returncode,0,compiled.stderr)
                executed = subprocess.run([str(root/'test')],cwd=root,capture_output=True,text=True)
                self.assertEqual(executed.returncode,0,executed.stderr)
                if app and os.environ.get('CLIP_DISPLAY_RENDER_DIR'):
                    out = Path(os.environ['CLIP_DISPLAY_RENDER_DIR']);out.mkdir(parents=True,exist_ok=True)
                    for name in ('upload-42.pbm','ota-42.pbm'):shutil.copy2(root/name,out/name)
