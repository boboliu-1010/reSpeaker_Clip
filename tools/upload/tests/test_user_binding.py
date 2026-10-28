"""Real C binding persistence and admission; hardware boundaries are adapters only."""
from pathlib import Path
import unittest
from test_auto_upload import compile_run, without_includes

ROOT = Path(__file__).resolve().parents[3]

CONFIG_PREAMBLE = r'''#define CONFIG_BOA_USER_BINDING 1
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <errno.h>
#include "upload_config.h"
typedef int (*settings_read_cb)(void*,void*,size_t);
struct settings_handler {const char *name;int (*h_set)(const char*,size_t,settings_read_cb,void*);};
static struct settings_handler *registered;
static unsigned char disk[1024];
static size_t disk_size;
static int write_error,writes,watches;
static uint32_t crc32_ieee(const uint8_t*p,size_t n){uint32_t c=~0u;while(n--){c^=*p++;for(int i=0;i<8;i++)c=(c>>1)^((c&1)?0xedb88320u:0);}return ~c;}
static void settings_load_watchdog_arm(void){assert(!watches);watches++;}
static void settings_load_watchdog_disarm(void){assert(watches);watches--;}
static int settings_register(struct settings_handler*h){registered=h;return 0;}
static int read_value(void*arg,void*out,size_t n){(void)arg;assert(n<=disk_size);memcpy(out,disk,n);return (int)n;}
static int settings_load_subtree(const char*key){assert(!strcmp(key,"https"));return disk_size?registered->h_set("config",disk_size,read_value,NULL):0;}
static int settings_save_one(const char*key,const void*p,size_t n){assert(!strcmp(key,"https/config"));writes++;if(write_error)return -EIO;assert(n<=sizeof(disk));memcpy(disk,p,n);disk_size=n;return 0;}
static int settings_delete(const char*key){assert(!strcmp(key,"https/config"));if(write_error)return -EIO;disk_size=0;return 0;}
'''


class UserBindingTest(unittest.TestCase):
    def test_v1_migration_crc_and_candidate_save_failure_preserve_live_record(self):
        # A v2-only loader would lose deployed Wi-Fi/token; mutating save's caller
        # before flash succeeds would corrupt the live record on error.
        code = CONFIG_PREAMBLE + without_includes(ROOT/'applications/clip/src/upload_config.c')
        code += r'''
struct deployed_v1 {uint32_t version,enabled;char ssid[33],password[64],host[96],port[6],device[33],token[97],clock_host[96],clock_port[6];uint8_t reserved;uint32_t crc;};
int main(void){
 struct deployed_v1 old={.version=1,.enabled=1,.ssid="phone-wifi",.password="wifi-password",.host="old.server",.port="9528",.device="clip01",.token="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",.clock_host="clock.server",.clock_port="123"};
 old.crc=crc32_ieee((const uint8_t*)&old,offsetof(struct deployed_v1,crc));memcpy(disk,&old,sizeof(old));disk_size=sizeof(old);
 struct upload_config value={0};assert(!upload_config_init(&value));
 assert(value.version==1&&value.enabled==1&&!strcmp(value.ssid,"phone-wifi")&&!strcmp(value.password,"wifi-password")&&!strcmp(value.token,old.token));
 struct upload_config before=value;
 write_error=1;assert(upload_config_save(&value)==-EIO);assert(!memcmp(&before,&value,sizeof(value)));assert(disk_size==sizeof(old));write_error=0;
 assert(!upload_config_save(&value));assert(value.version==2&&disk_size==sizeof(value));
 memset(&value,0,sizeof(value));assert(!upload_config_init(&value));assert(value.enabled&&!strcmp(value.ssid,"phone-wifi")&&!strcmp(value.host,"old.server"));
 disk[12]^=1;assert(upload_config_init(&value)==-EBADMSG&&!value.enabled);
 memcpy(disk,&old,sizeof(old));disk_size=sizeof(old);disk[12]^=1;assert(upload_config_init(&value)==-EBADMSG&&!value.enabled);
 assert(!watches);return 0;
}
'''
        compile_run(code)

    def test_binding_monotonic_idempotent_save_preserves_network_and_clear_is_checked(self):
        code = CONFIG_PREAMBLE + without_includes(ROOT/'applications/clip/src/upload_config.c')
        code += r'''
int main(void){
 const char *id="0123456789abcdef0123456789abcdef",*other="1123456789abcdef0123456789abcdef",*credential="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
 struct upload_config value={.enabled=1,.ssid="phone",.password="password",.host="old.server",.port="9528",.device="clip01",.token="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",.clock_host="clock",.clock_port="123"};
 assert(!upload_config_save(&value));
 struct upload_config before=value;write_error=1;
 assert(upload_config_bind(&value,"new.server","9528","clip01",credential,id,1,3)==-EIO);assert(!memcmp(&before,&value,sizeof(value)));write_error=0;
 assert(!upload_config_bind(&value,"new.server","9528","clip01",credential,id,1,3));
 assert(value.enabled&&!strcmp(value.ssid,"phone")&&!strcmp(value.password,"password")&&!strcmp(value.binding_id,id)&&value.epoch==1&&value.revision==3);
 int count=writes;assert(!upload_config_bind(&value,"new.server","9528","clip01",credential,id,1,3)&&writes==count);
 before=value;
 assert(upload_config_bind(&value,"old.server","9528","clip01",credential,id,1,2)==-ESTALE);
 assert(upload_config_bind(&value,"old.server","9528","clip01",credential,id,1,3)==-ESTALE);
 assert(upload_config_bind(&value,"new.server","9528","clip01",credential,id,2,4)==-ESTALE);
 assert(upload_config_bind(&value,"new.server","9528","clip01",credential,other,1,4)==-ESTALE);
 assert(upload_config_bind(&value,"new.server","9528","clip01",credential,id,0,4)==-EINVAL);
 assert(!memcmp(&before,&value,sizeof(value))&&writes==count);
 assert(!upload_config_bind(&value,"newer.server","9529","clip01",credential,id,1,4));
 before=value;write_error=1;assert(upload_config_unbind(&value,id,4)==-EIO);assert(!memcmp(&before,&value,sizeof(value)));write_error=0;
 assert(upload_config_unbind(&value,id,3)==-ESTALE);assert(upload_config_unbind(&value,other,4)==-ESTALE);
 assert(!upload_config_unbind(&value,id,4));assert(!value.enabled&&!value.host[0]&&!value.token[0]&&!value.binding_id[0]&&!value.epoch&&!value.revision&&!strcmp(value.ssid,"phone"));
 assert(upload_config_unbind(&value,id,4)==-ESTALE);
 assert(!upload_config_bind(&value,"new.server","9528","clip01",credential,id,1,5));
 assert(!upload_config_save_network(&value,"replacement","password"));assert(value.binding_id[0]&&value.revision==5);
 assert(!upload_config_save_receiver(&value,"legacy.server","9528","clip01",credential));assert(!value.binding_id[0]&&!value.epoch&&!value.revision);
 assert(!upload_config_bind(&value,"new.server","9528","clip01",credential,id,1,6));
 assert(!upload_config_forget(&value,UPLOAD_FORGET_RECEIVER));assert(!value.binding_id[0]&&!value.epoch&&!value.revision);
 return 0;
}
'''
        compile_run(code)

    def test_binding_admission_never_cancels_or_borrows_upload_reservation(self):
        code = r'''
#define CONFIG_BOA_USER_BINDING 1
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <errno.h>
#include <string.h>
#define AT_CMD_TYPE_SET 1
#define AT_CMD_TYPE_TEST 0
#define AT_CMD_TYPE_READ 3
typedef int atomic_t;
static int atomic_get(int*v){return *v;}
static void (*before_cas_hook)(void);
static bool atomic_cas(int*v,int before,int after){if(before_cas_hook){void(*hook)(void)=before_cas_hook;before_cas_hook=NULL;hook();}if(*v!=before)return false;*v=after;return true;}
'''
        code += without_includes(ROOT/'applications/clip/src/upload_command.c')
        code += r'''
int main(void){
 const char *commands[]={"BINDCFG","BINDCLR"};
 for(unsigned i=0;i<2;i++){
  assert(upload_command_claim_upload());
  assert(upload_command_begin(commands[i],1,true,true,false,false)==-EBUSY);
  assert(upload_command_begin(commands[i],1,true,false,false,false)==-EBUSY); /* active flag may lag reservation */
  upload_command_end();assert(!upload_command_claim_ota());upload_command_release_upload();
  assert(upload_command_begin(commands[i],1,false,false,false,false)==-EBUSY);
  assert(upload_command_begin(commands[i],1,true,false,true,false)==-EBUSY);
  assert(upload_command_begin(commands[i],1,true,false,false,true)==-EBUSY);
  assert(!upload_command_begin(commands[i],1,true,false,false,false));
  assert(!upload_command_claim_upload()&&!upload_command_claim_ota());
  assert(upload_command_binding_activate());
  assert(upload_command_begin("START",2,true,false,false,false)==-EBUSY);
  upload_command_end();assert(upload_command_claim_ota());upload_command_release_ota();
 }
 /* Native OTA and binding cannot interrupt a configuration write when the
  * uploader finishes concurrently: its reservation transfers to that write. */
 assert(upload_command_claim_upload());
 assert(!upload_command_begin("UPLOADAUTO",AT_CMD_TYPE_SET,true,true,false,false));
 upload_command_release_upload();
 assert(!upload_command_claim_ota());
 assert(upload_command_begin("BINDCFG",AT_CMD_TYPE_SET,true,false,false,false)==-EBUSY);
 upload_command_end();assert(upload_command_claim_ota());upload_command_release_ota();
 assert(upload_command_claim_upload());
 assert(!upload_command_begin("UPLOADAUTO",AT_CMD_TYPE_SET,true,true,false,false));
 before_cas_hook=upload_command_release_upload;upload_command_end();
 assert(upload_command_claim_ota());upload_command_release_ota();
 assert(upload_command_claim_upload());
 assert(!upload_command_begin("UPLOADAUTO",AT_CMD_TYPE_SET,true,true,false,false));
 before_cas_hook=upload_command_end;upload_command_release_upload();
 assert(upload_command_claim_ota());upload_command_release_ota();
 return 0;
}
'''
        compile_run(code)

    def test_identity_wire_and_binding_parser_limits_errors_and_secret_free_readback(self):
        code = CONFIG_PREAMBLE + without_includes(ROOT/'applications/clip/src/upload_config.c')
        code += r'''
#define AT_CMD_TYPE_SET 1
#define AT_CMD_TYPE_READ 3
#define AT_CMD_TYPE_TEST 0
struct at_cmd_ctx {const char*name;uint8_t type;const char*args;uint8_t transport_type;};
static int uid_error;
static int hwinfo_get_device_id(uint8_t*out,size_t n){assert(n>=8);if(uid_error)return -EIO;const uint8_t id[]={0x12,0x34,0x00,0x56,0x78,0x9a,0xbc,0xde};memcpy(out,id,8);return 8;}
'''
        code += without_includes(ROOT/'applications/clip/src/user_binding.c')
        code += r'''
static struct upload_config value={.clock_host="clock",.clock_port="123",.ssid="phone",.password="password",.host="old.server",.port="9528",.device="clip01",.token="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",.enabled=1};
static bool saved;
static void request(const char*name,const char*args,int type,int error){
 struct at_cmd_ctx ctx={.name=name,.args=args,.type=type};char out[512],expected[64];
 assert(user_binding_command(&ctx,&value,&saved,out,sizeof(out))>0);
 snprintf(expected,sizeof(expected),"\"error\":%d",error);assert(strstr(out,expected));
 assert(!strstr(out,"aaaaaaaaaaaaaaaa")&&!strstr(out,"password"));
 if(!error){
  assert(strstr(out,"\"device_uid\":\"12340056789abcde\""));
  if(!strcmp(name,"IDENTITY")){assert(strstr(out,"\"binding_protocol_version\":1")&&strstr(out,"reSpeaker Clip"));}
  else {assert(strstr(out,value.binding_id[0]?"\"bound\":true":"\"bound\":false"));}
 }
 if(!error&&!strcmp(name,"BINDCLR"))assert(strstr(out,"\"cleared_binding_id\":\"0123456789abcdef0123456789abcdef\""));
}
int main(void){
 request("IDENTITY",NULL,3,0);request("BINDING",NULL,3,0);
 request("BINDCFG","new.server,9528,clip01,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,0123456789abcdef0123456789abcdef,1,1",1,0);
 assert(saved&&value.enabled&&!strcmp(value.ssid,"phone"));
 request("BINDCFG","new.server,9528,clip01,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,0123456789abcdef0123456789abcdef,1,1",1,0);
 request("BINDCFG","other.server,9528,clip01,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,0123456789abcdef0123456789abcdef,1,1",1,-ESTALE);
 request("BINDCFG","new.server,9528,clip01,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,0123456789abcdef0123456789abcdef,1,4294967296",1,-EINVAL);
 request("BINDCFG","new.server,9528,clip01,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,0123456789abcdef0123456789abcdef,+1,2",1,-EINVAL);
 request("BINDCFG","new.server,9528,clip01,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,0123456789abcdef0123456789abcdef,1,2,extra",1,-EINVAL);
 request("BINDCLR","0123456789abcdef0123456789abcdef,2",1,-ESTALE);
 request("BINDCLR","0123456789abcdef0123456789abcdef,1",1,0);assert(!value.binding_id[0]&&!value.enabled&&value.ssid[0]);
 request("BINDING",NULL,3,0);
 /* The single AT write is measured including AT+ and '='. */
 char server[96],identity[33],credential[75],args[300];
 memset(server,'a',95);server[95]=0;memset(identity,'a',32);identity[32]=0;memset(credential,'b',73);credential[73]=0;
 snprintf(args,sizeof(args),"%s,9528,%s,%s,0123456789abcdef0123456789abcdef,1,9",server,identity,credential);
 assert(strlen(args)+11==255);request("BINDCFG",args,1,0);
 credential[73]='b';credential[74]=0;
 snprintf(args,sizeof(args),"%s,9528,%s,%s,0123456789abcdef0123456789abcdef,1,10",server,identity,credential);
 assert(strlen(args)+11>255);request("BINDCFG",args,1,-EINVAL);assert(value.revision==9);
 uid_error=1;request("IDENTITY",NULL,3,-EIO);
 return 0;
}
'''
        compile_run(code)

    def test_factory_rejects_failed_provisioning_clear_before_recording_erase(self):
        from test_baseline_responses import function
        source = (ROOT/'applications/clip/src/at_commands.c').read_text()
        code = r'''
#define CONFIG_BOA_USER_BINDING 1
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define K_MSEC(n) (n)
#define LOG_WRN(...) ((void)0)
struct at_cmd_ctx {const char*args;};
struct log_backend {int unused;};
static bool log_fs_active;
static int clear_error,cleared,defaults,erases,reboots;
int upload_runtime_factory_reset(void){cleared++;return clear_error;}
static int config_factory_reset(void){defaults++;return 0;}
static int storage_format_card(void){erases++;return 0;}
static const struct log_backend *log_backend_get_by_name(const char*n){(void)n;return NULL;}
static void log_backend_deactivate(const struct log_backend*b){(void)b;}
static void k_sleep(int n){(void)n;}
static void schedule_reboot(int n,bool bonds){assert(n==500&&bonds);reboots++;}
static int create_json_response(bool ok,const char*msg,const char*data,char*out,size_t n){(void)msg;(void)data;return snprintf(out,n,"%s",ok?"success":"failure");}
'''
        code += function(source,'static int cmd_factory_handler(')
        code += r'''
int main(void){
 struct at_cmd_ctx ctx={.args="confirm"};char out[128];
 clear_error=-EIO;assert(cmd_factory_handler(&ctx,out,sizeof(out))>0);
 assert(!strcmp(out,"failure")&&cleared==1&&!defaults&&!erases&&!reboots);
 clear_error=0;assert(cmd_factory_handler(&ctx,out,sizeof(out))>0);
 assert(!strcmp(out,"success")&&cleared==2&&defaults==1&&erases==1&&reboots==1);
 return 0;
}
'''
        compile_run(code)

    def test_runtime_factory_clear_failure_preserves_live_and_success_leaves_no_credentials(self):
        from test_baseline_responses import function
        code = CONFIG_PREAMBLE + without_includes(ROOT/'applications/clip/src/upload_config.c')
        code += r'''
#define K_FOREVER 0
#define CLIP_STATE_IDLE 0
static struct upload_config settings={.enabled=1,.ssid="phone",.password="password",.host="server",.port="9528",.device="clip01",.token="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",.clock_host="clock",.clock_port="123",.binding_id="0123456789abcdef0123456789abcdef",.epoch=1,.revision=1};
static bool config_saved=true;
static int control_lock,config_error,auto_paused,time_ready=1,device_state,initialized=1,snapshots;
static void publish_recording_origin(void){assert(control_lock);snapshots++;}
static int atomic_get(int*v){return *v;}
static uint32_t cursor_segment=9;
static char cursor_session[15]="20261028000000";
static bool upload_runtime_active(void){return false;}
static bool upload_runtime_record_pending(void){return false;}
static bool transfer_is_active(void){return false;}
static int clip_event_get_state(void){return device_state;}
static void k_mutex_lock(int*m,int timeout){(void)timeout;assert(!*m);*m=1;}
static void k_mutex_unlock(int*m){assert(*m);*m=0;}
static void atomic_set(int*v,int n){*v=n;}
static void atomic_clear(int*v){*v=0;}
'''
        code += function((ROOT/'applications/clip/src/upload_runtime.c').read_text(),'int upload_runtime_factory_reset(')
        code += r'''
int main(void){
 assert(!upload_config_save(&settings));struct upload_config before=settings;
 write_error=1;assert(upload_runtime_factory_reset()==-EIO);
 assert(!memcmp(&before,&settings,sizeof(before))&&config_saved&&!auto_paused&&time_ready&&disk_size&&!snapshots);
 write_error=0;device_state=1;assert(upload_runtime_factory_reset()==-EBUSY);assert(!memcmp(&before,&settings,sizeof(before)));
 device_state=0;assert(!upload_runtime_factory_reset());
 assert(!settings.ssid[0]&&!settings.password[0]&&!settings.host[0]&&!settings.token[0]&&!settings.binding_id[0]&&!settings.enabled&&!settings.epoch&&!settings.revision);
 assert(!config_saved&&auto_paused&&!time_ready&&!cursor_session[0]&&!cursor_segment&&!disk_size&&!control_lock&&snapshots==1);
 return 0;
}
'''
        compile_run(code)
