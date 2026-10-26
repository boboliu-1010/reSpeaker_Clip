"""Parse real baseline handler responses, not just command admission results."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]

def function(source, signature):
    start = source.index(signature)
    return source[start:source.index('\n}\n', start)+3]

class BaselineResponsesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        source = (ROOT/'applications/clip/src/at_commands.c').read_text()
        parser = (ROOT/'applications/clip/src/at_server.c').read_text()
        code = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#define AT_ERR_NOMEM 4
#define AT_CMD_TYPE_SET 1
#define AT_CMD_TYPE_TEST 0
#define AT_CMD_TYPE_READ 3
#define AT_OK 0
#define AT_ERR_PARSE 1
#define AT_ERR_PARAM 2
#define AT_CMD_TYPE_EXEC 2
#define CLIP_EVENT_STATUS_SHOW 1
#define MODE_NORMAL 0
#define MODE_ENHANCED 1
#define K_MSEC(v) (v)
#define LOG_WRN(...) ((void)0)
#define LOG_ERR(...) ((void)0)
struct at_cmd_ctx {uint8_t type;const char *args;};
struct storage_stats {uint32_t total_mb,free_space_mb;uint64_t total_bytes;bool is_mounted;};
static int storage_get_stats(struct storage_stats*s){*s=(struct storage_stats){.total_mb=100,.free_space_mb=60,.total_bytes=2*1024*1024,.is_mounted=true};return 0;}
enum recording_mode {normal=0,enhanced=1};
struct clip_context {struct {enum recording_mode mode;int auto_delete_days;unsigned oled_brightness;}config;};
static struct clip_context device={.config={.mode=normal,.auto_delete_days=-1,.oled_brightness=32}};
static struct clip_context *clip_get_context(void){return &device;}
static bool bonded;static int reset_calls,pair_reset_work;
static int ble_get_bond_addr(char *out,size_t n){if(!bonded)return -ENOENT;snprintf(out,n,"AA:BB:CC:DD:EE:FF");return 0;}
static int ble_clear_bonds(void){reset_calls++;return 0;}
static int settings_save(void){reset_calls++;return 0;}
static int k_work_schedule(int *w,int ms){(void)w;(void)ms;reset_calls++;return 1;}
static int config_set_mode(enum recording_mode v){device.config.mode=v;return 0;}
static int config_set_auto_delete_days(int v){device.config.auto_delete_days=v;return 0;}
static int config_set_oled_brightness(unsigned v){device.config.oled_brightness=v;return 0;}
static void clip_display_set_brightness(uint8_t v){(void)v;}
static void clip_post_event(int v){(void)v;}
static int config_set_wifi_channel(uint8_t v){(void)v;return 0;}
static int config_set_wifi_reg_domain(const char *v){(void)v;return 0;}
static unsigned config_get_wifi_channel(void){return 6;}
static const char *config_get_wifi_reg_domain(void){return "CN";}
'''
        code += function(parser, 'static const char *skip_whitespace(')
        code += function(parser, 'static int parse_command(')
        for name in ('create_json_response','cmd_storage_handler','extract_int','cmd_pair_handler','cmd_mode_handler',
                     'cmd_autodel_handler','cmd_brightness_handler','cmd_wificfg_handler'):
            code += function(source,'static int '+name+'(')
        code += r'''
int main(int argc,char **argv){
 assert(argc==2);struct at_cmd_ctx ctx={.type=AT_CMD_TYPE_TEST};char out[1024]={0};int n=0;
 if(!strncmp(argv[1],"storage-",8)){
  const char *wire=!strcmp(argv[1],"storage-read")?"AT+STORAGE?":!strcmp(argv[1],"storage-test")?"AT+STORAGE=?":!strcmp(argv[1],"storage-exec")?"AT+STORAGE":"AT+STORAGE=bad";
  char name[32]={0},args[256]={0};assert(!parse_command(wire,strlen(wire),name,args,&ctx.type));assert(!strcmp(name,"STORAGE"));ctx.args=args;
  n=cmd_storage_handler(&ctx,out,sizeof(out));
 }else if(!strcmp(argv[1],"paired")||!strcmp(argv[1],"unpaired")){
  bonded=!strcmp(argv[1],"paired");n=cmd_pair_handler(&ctx,out,sizeof(out));assert(!reset_calls);
 }else if(!strcmp(argv[1],"mode")){n=cmd_mode_handler(&ctx,out,sizeof(out));}
 else if(!strcmp(argv[1],"mode-set")){ctx.type=AT_CMD_TYPE_SET;ctx.args="enhanced";n=cmd_mode_handler(&ctx,out,sizeof(out));}
 else if(!strcmp(argv[1],"mode-error")){ctx.type=AT_CMD_TYPE_SET;ctx.args="invalid";n=cmd_mode_handler(&ctx,out,sizeof(out));}
 else if(!strcmp(argv[1],"autodel")){n=cmd_autodel_handler(&ctx,out,sizeof(out));}
 else if(!strcmp(argv[1],"autodel-set")){ctx.type=AT_CMD_TYPE_SET;ctx.args="7";n=cmd_autodel_handler(&ctx,out,sizeof(out));}
 else if(!strcmp(argv[1],"brightness")){n=cmd_brightness_handler(&ctx,out,sizeof(out));}
 else if(!strcmp(argv[1],"brightness-set")){ctx.type=AT_CMD_TYPE_SET;ctx.args="255";n=cmd_brightness_handler(&ctx,out,sizeof(out));}
 else if(!strcmp(argv[1],"wificfg")){n=cmd_wificfg_handler(&ctx,out,sizeof(out));}
 assert(n>0&&(size_t)n<sizeof(out));fwrite(out,1,(size_t)n,stdout);return 0;
}
'''
        (root/'test.c').write_text(code)
        cls.executable = root/'test'
        try:
            subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror',
                            '-Wno-unused-parameter','-Wno-sign-compare',
                            '-fsanitize=address,undefined',str(root/'test.c'),'-o',str(cls.executable)],check=True)
        except BaseException:
            cls.directory.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def response(self, case):
        wire=subprocess.check_output([str(self.executable),case],text=True)
        self.assertTrue(wire.endswith('\n'))
        return json.loads(wire)

    def test_pair_query_has_valid_json_and_preserves_legacy_msg_contract(self):
        self.assertEqual(self.response('paired'),{'ok':True,'msg':'"paired","addr":"AA:BB:CC:DD:EE:FF"'})
        self.assertEqual(self.response('unpaired'),{'ok':True,'msg':'"unpaired"'})

    def test_restored_settings_return_parseable_expected_values(self):
        cases={'mode':{'mode':'normal'},'mode-set':{'mode':'enhanced'},
               'autodel':{'autodel':'off'},'autodel-set':{'autodel':7},
               'brightness':{'brightness':32},'brightness-set':{'brightness':255},
               'wificfg':{'channel':6,'reg_domain':'CN'}}
        for case,expected in cases.items():
            with self.subTest(case=case):
                reply=self.response(case);self.assertTrue(reply['ok']);self.assertEqual(reply['data'],expected)
        self.assertFalse(self.response('mode-error')['ok'])

    def test_storage_queries_use_actual_at_parser_and_preserve_contract(self):
        expected={'mounted':True,'total_mb':100,'free_mb':60,'used_mb':40,'used_pct':40,'recorded_mb':2}
        for case in ('storage-read','storage-exec','storage-test'):
            with self.subTest(case=case):
                self.assertEqual(self.response(case),{'ok':True,'data':expected})
        self.assertFalse(self.response('storage-set')['ok'])
