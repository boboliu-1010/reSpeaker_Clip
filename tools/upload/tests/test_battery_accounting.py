"""Actual battery policy and JSON: distinguish Station work from idle and expose unknown load."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[3]
def function(s,name):
    a=s.index(name);return s[a:s.index('\n}\n',a)+3]

class BatteryAccountingTest(unittest.TestCase):
    def run_policy(self, station=True, configured=False):
        s=(ROOT/'applications/clip/src/battery.c').read_text()
        a=s.index('struct battery_load {');b=s.index('#ifdef CONFIG_CLIP_DEBUG_INTERFACES\nstatic struct',a)
        code=r'''
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <inttypes.h>
#include <errno.h>
#include <assert.h>
#include <math.h>
#define IS_ENABLED(v) (v)
#define CONFIG_CLIP_BATTERY_WIFI_LOAD_COMPENSATION 1
#define CONFIG_CLIP_BATTERY_WIFI_TX_LOAD_MA 99
#define CONFIG_CLIP_BATTERY_WIFI_AP_LOAD_MA 59
#define CONFIG_CLIP_BATTERY_IDLE_CURRENT_UA 400
static bool ap,transfer,audio;
static bool wifi_ap_is_running(void){return ap;}
static bool transfer_is_active(void){return transfer;}
static bool audio_is_recording(void){return audio;}
'''
        code+=f'#define CONFIG_CLIP_BATTERY_WIFI_STA_IDLE_LOAD_MA {30 if configured else 0}\n#define CONFIG_CLIP_BATTERY_WIFI_STA_ACTIVE_LOAD_MA {90 if configured else 0}\n'
        if station:
            code+='''
#define CONFIG_CLIP_UPLOAD 1
static bool job,up;
struct net_if{int dummy;};static struct net_if iface;
static bool upload_runtime_active(void){return job;}
static struct net_if *net_if_get_first_wifi(void){return &iface;}
static bool net_if_is_up(struct net_if*p){(void)p;return up;}
'''
        code+=s[a:b]
        code+='''
int main(void){
 struct battery_load l=battery_load_snapshot(false);assert(!l.active&&!l.wifi_ma&&!l.wifi_unmodeled);
 assert(fabsf(battery_model_current(-.025f,l)-.0004f)<.000001f);
 audio=true;l=battery_load_snapshot(false);assert(l.active);assert(fabsf(battery_model_current(-.025f,l)-.025f)<.000001f);audio=false;
 l=battery_load_snapshot(true);assert(l.active);assert(battery_model_current(.05f,l)<0);
 ap=true;l=battery_load_snapshot(false);assert(l.active&&l.wifi_ma==59&&!l.wifi_unmodeled);
 transfer=true;l=battery_load_snapshot(false);assert(l.wifi_ma==99);ap=false;transfer=false;
'''
        if station:
            code+='''
 job=true;l=battery_load_snapshot(false);assert(l.active&&!l.station_radio&&!l.wifi_ma&&!l.wifi_unmodeled);
 assert(fabsf(battery_model_current(-.025f,l)-.025f)<.000001f);
 up=true;l=battery_load_snapshot(false);assert(l.active&&l.station_radio&&l.station_job);
 assert(l.wifi_ma==CONFIG_CLIP_BATTERY_WIFI_STA_ACTIVE_LOAD_MA);
 assert(l.wifi_unmodeled==(CONFIG_CLIP_BATTERY_WIFI_STA_ACTIVE_LOAD_MA==0));
 assert(fabsf(battery_model_current(-.025f,l)-(.025f+CONFIG_CLIP_BATTERY_WIFI_STA_ACTIVE_LOAD_MA/1000.f))<.000001f);
 job=false;l=battery_load_snapshot(false);assert(l.active&&l.wifi_ma==CONFIG_CLIP_BATTERY_WIFI_STA_IDLE_LOAD_MA);
 up=false;l=battery_load_snapshot(false);assert(!l.active&&!l.wifi_unmodeled);
'''
        code+='''
 bool unknown;float f=battery_interval_current(&gauge_interval,.0004f,false,&unknown);assert(!unknown&&fabsf(f-.0004f)<.000001f);
 f=battery_interval_current(&gauge_interval,.025f,true,&unknown);assert(!unknown&&fabsf(f-.0004f)<.000001f);
 f=battery_interval_current(&gauge_interval,.025f,true,&unknown);assert(unknown&&fabsf(f-.025f)<.000001f);
 f=battery_interval_current(&gauge_interval,.0004f,false,&unknown);assert(unknown&&fabsf(f-.025f)<.000001f);
 f=battery_interval_current(&gauge_interval,.0004f,false,&unknown);assert(!unknown&&fabsf(f-.0004f)<.000001f);
 return 0;}
'''
        self.compile_run(code)

    def compile_run(self,code):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'test.c').write_text(code)
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test')],check=True)
            return subprocess.check_output([str(p/'test')],text=True)

    def test_station_job_never_uses_idle_current_and_unknown_compensation_is_visible(self):
        self.run_policy()
    def test_station_configuration_and_current_polarity(self):
        self.run_policy(configured=True)
    def test_baseline_without_station_feature_preserves_phone_and_ap_policy(self):
        self.run_policy(station=False)

    def test_actual_diagnostic_json_and_buffer_boundary(self):
        s=(ROOT/'applications/clip/src/battery.c').read_text();a=s.index('static struct {',s.index('static struct battery_interval gauge_interval;'));b=s.index('/* Piecewise-linear',a)
        # End at the diagnostic formatter's actual closing brace, not its #endif.
        diag=s[a:s.index('\n}\n',s.index('int battery_diag_format(',a))+3]
        code=r'''
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <inttypes.h>
#include <errno.h>
#include <assert.h>
#include <stdarg.h>
#include <string.h>
/* Model the target formatter contract: no long/long-long conversions. */
static int target_snprintf(char*out,size_t n,const char*fmt,...){
 assert(!strstr(fmt,"%l")&&!strstr(fmt,"%j"));
 va_list args;va_start(args,fmt);int result=vsnprintf(out,n,fmt,args);va_end(args);return result;
}
#define snprintf target_snprintf
#define K_FOREVER 0
static bool vbus_status_valid=true;static int32_t vbus_status_raw=16;
static int battery_mutex;static unsigned last_percent=99;
static int k_mutex_lock(int*p,int t){(void)p;(void)t;return 0;}
static int k_mutex_unlock(int*p){(void)p;return 0;}
static uint32_t k_uptime_get_32(void){return 1500;}
'''+diag+r'''
int main(void){char out[1024],tiny[8];
 battery_diag.valid=true;battery_diag.gauge_ready=true;battery_diag.sampled_ms=1000;
 battery_diag.station_job=true;battery_diag.station_radio=true;battery_diag.active=true;battery_diag.wifi_unmodeled=true;
 battery_diag.model_current_ua=25000;battery_diag.interval_current_ua=24000;battery_diag.raw_soc_milli_percent=99876;
 battery_diag.model_net_uas=-9000000000LL;battery_diag.unmodeled_wifi_ms=5000000000ULL;
 assert(battery_diag_format(tiny,sizeof(tiny))==-ENOSPC);
 int n=battery_diag_format(out,sizeof(out));assert(n>0&&n<(int)sizeof(out));fwrite(out,1,(size_t)n,stdout);
 battery_diag.model_net_uas=INT64_MIN;battery_diag.unmodeled_wifi_ms=UINT64_MAX;
 n=battery_diag_format(out,sizeof(out));assert(n>0);fwrite(out,1,(size_t)n,stdout);
 char text[22];battery_counter_text(text,0,false);assert(!strcmp(text,"0"));
 return 0;}
'''
        lines=self.compile_run(code).splitlines();v=json.loads(lines[0])['data']
        limits=json.loads(lines[1])['data'];self.assertEqual(limits['model_net_uas'],-(1<<63));self.assertEqual(limits['unmodeled_wifi_ms'],(1<<64)-1)
        self.assertEqual(v['age_ms'],500);self.assertEqual(v['raw_soc_milli_percent'],99876)
        self.assertEqual(v['display_percent'],99);self.assertTrue(v['wifi_unmodeled'])
        self.assertTrue(v['vbus_valid']);self.assertEqual(v['vbus_status_raw'],16)
        self.assertFalse(v['energy_calibrated']);self.assertEqual(v['model_net_uas'],-9000000000)
        self.assertEqual(v['unmodeled_wifi_ms'],5000000000)

    def test_diagnostic_registration_is_absent_in_production(self):
        s=(ROOT/'applications/clip/src/at_commands.c').read_text();a=s.index('#ifdef CONFIG_CLIP_DEBUG_INTERFACES\n    static const struct at_command battdiag_cmd');b=s.index('#endif',a)+6;registration=s[a:b]
        for debug in (False,True):
            code='''#include <stdio.h>\n#define AT_CMD_QUERY 2\n#define AT_CMD_EXEC 4\nstruct at_command {const char*name;int flags;int(*handler)(void);};\nstatic int at_server_register_cmd(const struct at_command*c){puts(c->name);return 0;}\nstatic int cmd_battdiag_handler(void){return 0;}\n'''
            if debug:code+='#define CONFIG_CLIP_DEBUG_INTERFACES 1\n'
            code+='int main(void){int err=0;(void)at_server_register_cmd;(void)cmd_battdiag_handler;\n'+registration+'\nreturn err;}\n'
            self.assertEqual(self.compile_run(code).strip(),'BATTDIAG' if debug else '')

    def test_vbus_uses_driver_present_attribute_not_other_status_bits(self):
        s=(ROOT/'applications/clip/src/battery.c').read_text()
        code=r'''
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>
#include <assert.h>
#define CONFIG_CLIP_DEBUG_INTERFACES 1
#define SENSOR_CHAN_NPM13XX_CHARGER_VBUS_STATUS 9
#define SENSOR_ATTR_NPM13XX_CHARGER_VBUS_PRESENT 11
struct sensor_value{int32_t val1,val2;};
static int charger_dev,raw,error,attr_calls;
static bool vbus_status_valid;static int32_t vbus_status_raw;
static int sensor_channel_get(int dev,int chan,struct sensor_value*v){assert(dev==charger_dev&&chan==9);v->val1=raw;return 0;}
static int sensor_attr_get(int dev,int chan,int attr,struct sensor_value*v){assert(dev==charger_dev&&chan==9&&attr==11);attr_calls++;if(error)return -EIO;v->val1=raw&1;return 0;}
'''+function(s,'static bool poll_vbus_status(')+r'''
int main(void){for(raw=0;raw<256;raw++){bool p=poll_vbus_status();assert(vbus_status_valid&&p==((raw&1)!=0)&&vbus_status_raw==raw);}
 assert(attr_calls==256);error=1;assert(!poll_vbus_status()&&!vbus_status_valid);return 0;}
'''
        self.compile_run(code)
