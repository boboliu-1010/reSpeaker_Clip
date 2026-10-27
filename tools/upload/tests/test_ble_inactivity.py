"""Compile real BLE timeout/refresh code with a fake clock and connection lifecycle."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]


class BleInactivityTest(unittest.TestCase):
    def test_activity_queued_timeout_disconnect_failure_and_reconnect(self):
        source = (ROOT/'applications/clip/src/ble.c').read_text()
        begin = source.index('static void inactivity_start(')
        end = source.index('/* Advertising restart handler */', begin)
        refresh = 'void ble_activity_refresh(void)' + source.split('void ble_activity_refresh(void)', 1)[1]
        code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#define BLE_INACTIVITY_TIMEOUT_MS 300000
#define K_MSEC(x) (x)
#define ARG_UNUSED(x) (void)(x)
#define LOG_INF(...) ((void)0)
#define BT_HCI_ERR_REMOTE_USER_TERM_CONN 19
struct bt_conn {int id; int refs;};
struct k_spinlock {int unused;};
struct k_work {int unused;};
typedef int k_spinlock_key_t;
static struct k_spinlock inactivity_lock;
static struct bt_conn *inactivity_conn, *last_closed;
static int64_t last_activity_ms, now, due;
static bool inactivity_closing, scheduled, replace_on_close;
static int inactivity_work, locked, disconnects, close_error;
static struct bt_conn a={1,1}, b={2,1};
static void inactivity_start(struct bt_conn *);
static void inactivity_stop(struct bt_conn *);
void ble_activity_refresh(void);
static int64_t k_uptime_get(void){return now;}
static int k_spin_lock(struct k_spinlock *p){(void)p;assert(!locked);locked=1;return 0;}
static void k_spin_unlock(struct k_spinlock *p,int key){(void)p;(void)key;assert(locked);locked=0;}
static void k_work_reschedule(int *p,int64_t delay){(void)p;assert(locked&&delay>0);due=now+delay;scheduled=true;}
static void k_work_cancel_delayable(int *p){(void)p;assert(locked);scheduled=false;}
static struct bt_conn *bt_conn_ref(struct bt_conn *c){assert(locked&&c->refs>0);c->refs++;return c;}
static void bt_conn_unref(struct bt_conn *c){assert(!locked&&c->refs>0);c->refs--;}
static int bt_conn_disconnect(struct bt_conn *c,int reason){
 assert(!locked&&reason==19&&c->refs>=2);disconnects++;last_closed=c;
 /* Activity after the close decision cannot revive a closing connection. */
 ble_activity_refresh();
 if(replace_on_close){
  replace_on_close=false;inactivity_stop(c);c->refs--;
  inactivity_start(&a);
 }
 return close_error;
}
'''
        code += source[begin:end] + refresh
        code += r'''
int main(void){
 inactivity_timeout_handler(NULL);ble_activity_refresh();assert(!scheduled&&!disconnects);
 inactivity_start(&a);assert(due==300000);
 now=1000;ble_activity_refresh();assert(due==301000);
 /* A timeout queued before the refresh must not disconnect. */
 now=300000;inactivity_timeout_handler(NULL);assert(!disconnects&&due==301000);
 /* Meaningful traffic continues for >5 minutes without losing the link. */
 for(int i=0;i<12;i++){now+=60000;ble_activity_refresh();inactivity_timeout_handler(NULL);assert(!disconnects);}
 now+=299999;inactivity_timeout_handler(NULL);assert(!disconnects&&due==now+1);
 now++;inactivity_timeout_handler(NULL);
 assert(disconnects==1&&last_closed==&a&&a.refs==1&&inactivity_closing);
 inactivity_stop(&a);assert(!scheduled&&!inactivity_conn&&!inactivity_closing);
 /* HCI failure must permit future activity and another timeout attempt. */
 now=0;inactivity_start(&a);now=300000;close_error=-5;
 inactivity_timeout_handler(NULL);assert(disconnects==2&&!inactivity_closing&&due==600000&&a.refs==1);
 now+=10;ble_activity_refresh();inactivity_timeout_handler(NULL);assert(disconnects==2&&due==600010);
 inactivity_stop(&a);
 /* A late old callback cannot cancel or disconnect the new connection. */
 now=700000;inactivity_start(&b);inactivity_stop(&a);
 inactivity_timeout_handler(NULL);assert(disconnects==2&&inactivity_conn==&b&&due==1000000);
 now=1000000;replace_on_close=true;
 inactivity_timeout_handler(NULL);
 assert(disconnects==3&&last_closed==&b&&b.refs==0);
 assert(inactivity_conn==&a&&!inactivity_closing&&due==1300000);
 inactivity_stop(&a);assert(!scheduled&&!locked);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'test.c').write_text(code)
            result = subprocess.run(['clang', '-std=c11', '-fsanitize=address,undefined',
                                     str(root/'test.c'), '-o', str(root/'test')],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run([str(root/'test')], check=True, capture_output=True)
