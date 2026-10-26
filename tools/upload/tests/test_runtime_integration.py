"""Exercise the firmware command policy."""
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]


class RuntimeIntegrationTest(unittest.TestCase):
    def command_fixture(self):
        source = (ROOT / "applications/clip/src/upload_runtime.c").read_text()
        parsing = "static char *split_field" + source.split("static char *split_field", 1)[1].split(
            "static void request_cancel", 1)[0]
        parsing += "static bool valid_id" + source.split("static bool valid_id", 1)[1].split(
            "static int hash_file", 1)[0]
        handlers = "static int configure_network" + source.split("static int configure_network", 1)[1].split(
            "int upload_runtime_register", 1)[0]
        code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <errno.h>
#define TRANSPORT_TYPE_USB 1
#define CONFIG_CLIP_DEBUG_INTERFACES 1
#define TRANSPORT_TYPE_BLE 3
#define CLIP_STATE_IDLE 0
#define AT_CMD_TYPE_SET 1
#define AT_CMD_TYPE_TEST 0
#define AT_CMD_TYPE_EXEC 2
#define AT_CMD_TYPE_READ 3
#define CLOCK_REALTIME 0
#define CLIP_EVENT_UPLOAD_BEGIN 1
#define CLIP_EVENT_OK 0
struct timespec { long long tv_sec; long tv_nsec; };
struct at_cmd_ctx { int transport_type, type; const char *name, *args; };
struct clip_event_result_info { int result; };
struct wifi_station_network { char ip[16], netmask[16], gateway[16]; };
static int active, cancelled, stalled, last_error, bytes_sent, stage, tls_step, start_job;
static int confirmed, resume_from, total_bytes;
static int state_error, state_queries, datagram_received;
#include "upload_config.h"
static struct upload_config settings = {.clock_host="clock", .clock_port="123"};
#define ssid settings.ssid
#define password settings.password
#define host settings.host
#define port settings.port
#define device_id settings.device
#define token settings.token
static char session[32];
static int auto_job, auto_paused, config_error, scan_error, control_lock, save_error;
static bool config_saved;
static int device_state, save_count;
static struct upload_config saved_settings;
static int clip_event_get_state(void) { return device_state; }
static unsigned int failures, cursor_segment;
static char cursor_session[15];
static long long next_auto, time_synced_at;
#define K_FOREVER 0
#define MAX(a,b) ((a)>(b)?(a):(b))
static long long k_uptime_get(void) { return 123; }
static void k_mutex_lock(int *m,int wait) { assert(!*m);*m=1;(void)wait; }
static void k_mutex_unlock(int *m) { assert(*m);*m=0; }
static void atomic_set(int *v,int n) { *v=n; }
static void atomic_clear(int *v) { *v=0; }
int upload_config_save(struct upload_config *c) { save_count++; if(!save_error)saved_settings=*c; return save_error; }
int upload_config_clear(void) { return save_error; }
int upload_config_valid(const struct upload_config *c) { (void)c;return 1; }
static int list_states(const char *a,char *o,size_t n) { (void)a;(void)o;(void)n;return -ENOENT; }
static uint32_t segment;
static int time_ready;
static const char *names[] = {"idle", "preparing"}, *tls_steps[] = {"idle"};
enum { PREPARING = 1 };
static int event_error, event_result, interrupts, resets, starts, clock_error;
static long long wall_time;
static bool upload_runtime_active(void) { return active; }
static bool upload_runtime_record_pending(void) { return false; }
static int atomic_get(int *v) { return *v; }
static void request_cancel(void) { cancelled = 1; interrupts++; }
static int state_query(const char *args, char *out, size_t length) {
    assert(args && out && length); state_queries++; return -ENOENT;
}
static void wifi_diag_reset(void) { resets++; }
static void k_sem_give(int *sem) { (*sem)++; starts++; }
static const char *wifi_station_last_step(void) { return "idle"; }
static void wifi_station_get_network(struct wifi_station_network *n) { memset(n, 0, sizeof(*n)); }
static int clip_post_event_sync(int event, struct clip_event_result_info *result) {
    assert(event == CLIP_EVENT_UPLOAD_BEGIN); result->result = event_result;
    if (!event_error && !event_result) {
        active = true; cancelled = stalled = last_error = bytes_sent = 0; stage = PREPARING;
    }
    return event_error;
}
static int clock_settime(int clock, const struct timespec *ts) {
    assert(clock == CLOCK_REALTIME);
    if (clock_error) { errno = EIO; return -1; }
    wall_time = ts->tv_sec; return 0;
}
'''
        # Compile the real transactional persistence helper without the legacy
        # uploader's field-name macros, as in its own production C module.
        config_source = (ROOT / "applications/clip/src/upload_config.c").read_text()
        network_save = 'int upload_config_save_network' + config_source.split('int upload_config_save_network', 1)[1]
        code += '#undef ssid\n#undef password\n#undef host\n#undef port\n#undef token\n' + network_save
        code += '\n#define ssid settings.ssid\n#define password settings.password\n#define host settings.host\n#define port settings.port\n#define token settings.token\n' + parsing + handlers
        code += r'''
static void request(const char *name, const char *args, int transport, int type, int expected) {
    struct at_cmd_ctx ctx = {.name=name, .args=args, .transport_type=transport, .type=type};
    char response[1024], error[32];
    int n = command(&ctx, response, sizeof(response));
    assert(n > 0 && (size_t)n == strlen(response));
    snprintf(error, sizeof(error), "\"error\":%d,", expected);
    assert(strstr(response, error));
    assert(strstr(response, expected ? "\"ok\":false" : "\"ok\":true"));
    assert(!strstr(response, "test-password"));
}
int main(void) {
    request("NETCFG", "test,test-password", 0, AT_CMD_TYPE_SET, -EACCES);
    assert(!ssid[0]);
    request("NETCFG", "test,short", 1, AT_CMD_TYPE_SET, -EINVAL);
    request("NETCFG", "test,test-password", 1, AT_CMD_TYPE_SET, 0);
    assert(!strcmp(ssid, "test") && !strcmp(password, "test-password"));
    /* BLE is limited to encrypted-GATT network provisioning, not upload admin.
     * A failed save leaves both the live settings and prior saved flag intact. */
    struct upload_config prior=settings;
    save_error=-EIO;
    request("NETCFG", "phone,test-password", 3, AT_CMD_TYPE_SET, -EIO);
    assert(!memcmp(&settings,&prior,sizeof(settings))&&config_saved);
    save_error=0;
    request("NETCFG", "phone\"net,test-password,comma", 3, AT_CMD_TYPE_SET, 0);
    assert(config_saved&&!strcmp(ssid,"phone\"net")&&!strcmp(password,"test-password,comma"));
    assert(!memcmp(&settings,&saved_settings,sizeof(settings)));
    int count=save_count;
    request("NETCFG", "phone\"net,test-password,comma", 3, AT_CMD_TYPE_SET, 0);
    assert(save_count==count); /* Repeated provisioning does not wear flash. */
    request("NETCFG", NULL, 3, 0, 0);
    prior=settings;save_error=-EIO;
    request("NETCFG", "new,test-password", 3, AT_CMD_TYPE_SET, -EIO);
    assert(config_saved&&!memcmp(&settings,&prior,sizeof(settings)));
    save_error=0;
    request("NETCFG", "bad,test\npassword", 3, AT_CMD_TYPE_SET, -EINVAL);
    request("NETCFG", "bad,short", 3, AT_CMD_TYPE_SET, -EINVAL);
    device_state=1;
    request("NETCFG", "busy,test-password", 3, AT_CMD_TYPE_SET, -EBUSY);
    device_state=0;active=1;
    request("NETCFG", "busy,test-password", 3, AT_CMD_TYPE_SET, -EBUSY);
    active=0;
    request("UPLOADAUTO", "on", 3, AT_CMD_TYPE_SET, -EACCES);
    request("UPLOADCFG", "receiver,8443,fixture,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 3, AT_CMD_TYPE_SET, -EACCES);
    request("NETCFG", "bad,test-password", 0, AT_CMD_TYPE_SET, -EACCES);
    request("NETCFG", "test,test-password", 1, AT_CMD_TYPE_SET, 0);
    assert(config_saved); /* Both transports now persist each configuration. */
    request("UPLOADCFG", "receiver,8443,fixture", 1, AT_CMD_TYPE_SET, -EINVAL);
    request("UPLOADCFG", "receiver,0,fixture,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 1, AT_CMD_TYPE_SET, -EINVAL);
    assert(!host[0]);
    request("UPLOADCFG", "receiver,8443,fixture,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", 1, AT_CMD_TYPE_SET, 0);
    assert(!strcmp(host, "receiver") && !strcmp(port, "8443"));
    request("UPLOADSTATE", "20261019070446:1", 1, AT_CMD_TYPE_SET, -ENOENT);
    assert(state_queries == 1);
    assert(upload_runtime_set_time(0)==-EINVAL);
    clock_error = 1;
    assert(upload_runtime_set_time(1800000000)==-EIO);
    assert(!time_ready);
    clock_error = 0;
    assert(upload_runtime_set_time(1800000000)==0);
    assert(time_ready && wall_time == 1800000000LL);
    request("UPLOAD", "20261019070446:0", 1, AT_CMD_TYPE_SET, -EINVAL);
    request("UPLOAD", "session:1", 1, AT_CMD_TYPE_SET, -EINVAL);
    request("UPLOAD", "2026101907044x:1", 1, AT_CMD_TYPE_SET, -EINVAL);
    event_error = -EIO;
    request("UPLOAD", "20261019070446:1", 1, AT_CMD_TYPE_SET, -EBUSY);
    event_error = 0; event_result = 1;
    request("UPLOAD", "20261019070446:1", 1, AT_CMD_TYPE_SET, -EBUSY);
    assert(!starts && !resets);
    event_result = 0; cancelled = stalled = last_error = bytes_sent = 1;
    request("UPLOAD", "20261019070446:1", 1, AT_CMD_TYPE_SET, 0);
    assert(active && starts == 1 && resets == 1 && stage == PREPARING);
    assert(upload_runtime_set_time(1800000100)==-EBUSY&&wall_time==1800000000LL);
    request("UPLOADSTATE", "20261019070446:1", 1, AT_CMD_TYPE_SET, -EBUSY);
    assert(state_queries == 1);
    assert(segment == 1 && !strcmp(session, "20261019070446"));
    assert(!cancelled && !stalled && !last_error && !bytes_sent);
    request("UPLOAD", NULL, 1, 0, 0);
    request("NETCFG", "other,test-password", 1, AT_CMD_TYPE_SET, -EBUSY);
    assert(!strcmp(ssid, "test"));
    request("UPLOADCANCEL", NULL, 1, 0, 0);
    assert(cancelled && interrupts == 1 && auto_paused);
    active = 0;
    request("UPLOADAUTO", "on", 1, AT_CMD_TYPE_SET, 0);
    assert(settings.enabled && config_saved && !auto_paused);
    request("NETCFG", "other,test-password", 1, AT_CMD_TYPE_SET, 0);
    request("NETCFG", "phone,test-password", 3, AT_CMD_TYPE_SET, 0);
    assert(settings.enabled&&config_saved&&!strcmp(ssid,"phone"));
    auto_job = active = 1;
    request("UPLOADAUTO", "off", 1, AT_CMD_TYPE_SET, 0);
    assert(!settings.enabled && auto_paused && cancelled);
    active = 0; save_error = -EIO;
    request("UPLOADAUTO", "on", 1, AT_CMD_TYPE_SET, -EIO);
    assert(!settings.enabled && config_saved && auto_paused);
    save_error = 0;
    request("UPLOADCLEAR", NULL, 1, 0, 0);
    assert(!ssid[0] && !host[0] && !config_saved);
    return 0;
}
'''
        return code

    def test_command_dispatch_preserves_validation_busy_cancel_and_start(self):
        code = self.command_fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test.c").write_text(code)
            subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-fsanitize=address,undefined", "-I"+str(ROOT / "applications/clip/include"), str(root / "test.c"),
                            "-o", str(root / "test")], check=True)
            subprocess.run([str(root / "test")], check=True)

    def test_app_ble_controls_validation_and_diagnostic_boundary(self):
        from test_auto_upload import compile_run
        source = (ROOT/'applications/clip/src/upload_app.c').read_text()
        formatting = source[source.index('int upload_app_format_status'):source.index('static void enqueue')]
        code = self.command_fixture().split('static void request(', 1)[0]
        at = code.index('static int configure_network')
        adapter = r'''
#include "upload_app.h"
#define CONNECTING PREPARING
static int checking_network,app_enabled,app_job_network;
static uint32_t app_job;
static long long deadline;
static struct upload_app_network network={.state="idle"};
static void app_reset_network(const char*s){memset(&network,0,sizeof(network));network.state=s;}
void upload_runtime_app_network(struct upload_app_network*out){*out=network;}
void upload_runtime_app_status(struct upload_app_status*out){memset(out,0,sizeof(*out));out->stage="idle";out->enabled=settings.enabled;out->paused=auto_paused;}
'''
        code = '#define CONFIG_CLIP_UPLOAD_APP 1\n'+code[:at]+adapter+formatting+code[at:]
        code += r'''
static char response[1024];
static void q(const char *name,const char *args,int transport,int type,int error){
 struct at_cmd_ctx ctx={.name=name,.args=args,.transport_type=transport,.type=type};
 int n=command(&ctx,response,sizeof(response));assert(n>0&&(size_t)n==strlen(response));
 if(error){char expected[30];snprintf(expected,sizeof(expected),"\"error\":%d,",error);assert(strstr(response,expected));}
 else assert(strstr(response,"\"ok\":true"));
 assert(!strstr(response,"test-password")&&!strstr(response,"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"));
}
int main(void){
 q("NETCFG","test,test-password",3,1,0);assert(config_saved);
 q("UPLOADCFG","receiver,9527,fixture,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",1,1,0);
 assert(config_saved);
 q("UPLOADAUTO","on",3,1,0);assert(settings.enabled&&app_enabled&&!auto_paused);
 int count=save_count;q("UPLOADAUTO","on",3,1,0);assert(count==save_count);
 q("UPLOADAUTO",NULL,3,3,0);assert(strstr(response,"\"enabled\":true"));
 q("UPLOAD",NULL,3,3,0);assert(strstr(response,"\"kind\":\"upload\""));
 q("UPLOAD","20261024054528:1",3,1,-EACCES);
 q("UPLOADCFG",NULL,3,3,0);assert(strstr(response,"\"configured\":true"));
 q("UPLOADCFG","receiver,9527,fixture,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",3,1,-EBUSY);
 q("UPLOADPERF","on",3,1,-EACCES);
 q("NETCHECK",NULL,0,2,-EACCES);
 active=auto_job=1;cancelled=0;save_error=-EIO;
 q("UPLOADAUTO","off",3,1,-EIO);assert(settings.enabled&&!auto_paused&&!cancelled);
 save_error=0;q("UPLOADAUTO","off",3,1,0);assert(!settings.enabled&&auto_paused&&cancelled&&!app_enabled);
 q("NETCHECK",NULL,3,2,-EBUSY);
 cancelled=0;q("NETCHECK","cancel",3,1,0);assert(!cancelled); /* Never cancels an unrelated upload. */
 q("NETCFG",NULL,3,3,0); /* Read-only configuration remains available while active. */
 q("NETCFG","new,test-password",3,1,-EBUSY);
 active=auto_job=0;cancelled=0;
 q("NETCHECK",NULL,3,2,0);assert(active&&checking_network&&app_job_network&&starts==1&&deadline>123);
 assert(strstr(response,"\"accepted\":true"));
 q("NETCHECK",NULL,3,3,0);assert(strstr(response,"checking"));
 q("NETCHECK","cancel",3,1,0);assert(cancelled);
 q("NETCHECK","bad",3,1,-EINVAL);
 active=checking_network=0;
 q("NETCFG","new,test-password",3,1,0);assert(!strcmp(network.state,"idle"));
 return 0;
}
'''
        compile_run(code)

    def test_cleanup_before_radio_start_is_safe_and_idempotent(self):
        source = (ROOT / "applications/clip/src/wifi_station.c").read_text()
        cleanup = source.split("int wifi_off(void)", 1)[1].split(
            "bool wifi_is_interface_up", 1)[0]
        code = '''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <errno.h>
#include "wifi_diag.h"
#define CONFIG_NRF70_SR_COEX 1
#define NET_REQUEST_WIFI_DISCONNECT 1
struct net_if { bool up; };
static struct net_if radio;
static bool present = true;
static int got_ip, disconnects, dhcp_stops, resets, downs;
static struct net_if *net_if_get_first_wifi(void) { return present ? &radio : NULL; }
static bool net_if_is_admin_up(struct net_if *iface) { return iface->up; }
static void atomic_clear(int *value) { *value = 0; }
static int net_mgmt(int request, struct net_if *iface, void *data, size_t length) {
    assert(request == NET_REQUEST_WIFI_DISCONNECT && iface->up);
    assert(data == NULL && length == 0); disconnects++; return 0;
}
static void net_dhcpv4_stop(struct net_if *iface) { assert(iface->up); dhcp_stops++; }
static void nrf_wifi_coex_hw_reset(void) { assert(radio.up); resets++; }
static int net_if_down(struct net_if *iface) { iface->up = false; downs++; return 0; }
'''
        code += "int wifi_off(void)" + cleanup
        code += '''
int main(void) {
    got_ip = 1;
    assert(wifi_off() == 0 && got_ip == 0);
    assert(disconnects == 0 && dhcp_stops == 0 && resets == 0 && downs == 0);
    radio.up = true; got_ip = 1;
    assert(wifi_off() == 0 && got_ip == 0 && !radio.up);
    assert(disconnects == 1 && dhcp_stops == 1 && resets == 1 && downs == 1);
    assert(wifi_off() == 0);
    assert(disconnects == 1 && dhcp_stops == 1 && resets == 1 && downs == 1);
    present = false;
    assert(wifi_off() == -ENODEV);
    return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test.c").write_text(code)
            subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-fsanitize=address,undefined", "-I"+str(ROOT / "applications/clip/include"), str(root / "test.c"),
                            "-o", str(root / "test")], check=True)
            subprocess.run([str(root / "test")], check=True)

    def test_baseline_commands_and_upload_admission(self):
        source = (ROOT / "applications/clip/src/upload_command.c").read_text()
        policy = '\n'.join(line for line in source.splitlines() if not line.startswith('#include'))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            code = r'''
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <assert.h>
#include <errno.h>
#include <stdatomic.h>
#define AT_CMD_TYPE_TEST 0
#define AT_CMD_TYPE_SET 1
#define AT_CMD_TYPE_EXEC 2
#define AT_CMD_TYPE_READ 3
typedef atomic_int atomic_t;
static int atomic_get(atomic_t *p) {return atomic_load(p);}
static bool atomic_cas(atomic_t *p,int old,int value) {return atomic_compare_exchange_strong(p,&old,value);}
'''
            code += policy + r'''
int main(void) {
    const char *baseline[]={"GSTAT","BATT","STORAGE","DEVICE","VERSION","TIME","MODE","AUTODEL",
      "BRIGHTNESS","POWEROFF","FACTORY","PAIR","REBOOT","DFU","START","STOP","PAUSE","RESUME",
      "MARK","LIST","MARKS","DOWNLOAD","CANCEL","DELETE","FORMAT","WIFI","WIFICFG","NAME","USB","LOG"};
    for (unsigned i=0;i<sizeof(baseline)/sizeof(*baseline);i++) {
        assert(!upload_command_begin(baseline[i],AT_CMD_TYPE_SET,true,false,false,false));
        upload_command_end();
        assert(upload_command_claim_upload());upload_command_release_upload();
    }
    const char *reads[]={"DEVICE","MODE","AUTODEL","BRIGHTNESS","NAME","PAIR","WIFI","WIFICFG",
      "TIME","USB","LOG","GSTAT","BATT","VERSION","RES","NETDIAG","NETTRACE","NETTX",
      "UPLOADNET","UPLOADPERF","UPLOAD","NETCFG","UPLOADAUTO"};
    assert(upload_command_claim_upload());
    for (unsigned i=0;i<sizeof(reads)/sizeof(*reads);i++) {
        assert(!upload_command_begin(reads[i],AT_CMD_TYPE_READ,true,true,false,false));
        upload_command_end();assert(!upload_command_claim_upload());
    }
    const char *blocked[]={"MODE","AUTODEL","BRIGHTNESS","NAME","PAIR","WIFI","WIFICFG","TIME",
      "USB","LOG","DELETE","FORMAT","DOWNLOAD","CANCEL","FACTORY","REBOOT","DFU","POWEROFF",
      "PAUSE","RESUME","MARK","LIST","MARKS","STORAGE"};
    for (unsigned i=0;i<sizeof(blocked)/sizeof(*blocked);i++) {
        assert(upload_command_begin(blocked[i],AT_CMD_TYPE_SET,true,true,false,false)==-EBUSY);
    }
    assert(!upload_command_begin("START",AT_CMD_TYPE_EXEC,true,true,false,false));
    assert(!upload_command_begin("STOP",AT_CMD_TYPE_EXEC,true,true,false,false));
    upload_command_release_upload();
    /* A baseline command reserves storage before auto-upload can start. */
    assert(!upload_command_begin("DELETE",AT_CMD_TYPE_SET,true,false,false,false));
    assert(!upload_command_claim_upload());upload_command_end();
    assert(upload_command_claim_upload());upload_command_release_upload();
    /* Pending recording and ongoing download reject conflicting operations. */
    assert(upload_command_begin("MODE",AT_CMD_TYPE_SET,true,false,true,false)==-EBUSY);
    assert(upload_command_begin("FORMAT",AT_CMD_TYPE_EXEC,false,false,false,true)==-EBUSY);
    assert(!upload_command_begin("CANCEL",AT_CMD_TYPE_EXEC,false,false,false,true));upload_command_end();
    assert(!upload_command_begin("PAUSE",AT_CMD_TYPE_EXEC,false,false,false,false));
    assert(!upload_command_begin("RESUME",AT_CMD_TYPE_EXEC,false,false,false,false));
    assert(!upload_command_begin("MARK",AT_CMD_TYPE_EXEC,false,false,false,false));
    /* Delayed erase/reboot keeps its reservation after the AT reply. */
    assert(!upload_command_begin("PAIR",AT_CMD_TYPE_SET,true,false,false,false));
    upload_command_defer();upload_command_end();
    assert(!upload_command_claim_upload());
    assert(!upload_command_begin("MODE",AT_CMD_TYPE_READ,true,false,false,false));upload_command_end();
    assert(upload_command_begin("START",AT_CMD_TYPE_EXEC,true,false,false,false)==-EBUSY);
    assert(upload_command_begin("DELETE",AT_CMD_TYPE_SET,true,false,false,false)==-EBUSY);
    assert(!upload_command_claim_upload());
    return 0;
}
'''
            (root / "test.c").write_text(code)
            subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-fsanitize=address,undefined", str(root / "test.c"),
                            "-o", str(root / "test")], check=True)
            subprocess.run([str(root / "test")], check=True)



if __name__ == "__main__":
    unittest.main()
