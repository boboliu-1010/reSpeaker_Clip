"""The stock TIME handler must update the upload clock before committing UI time."""
from pathlib import Path
import unittest
from test_auto_upload import compile_run

ROOT = Path(__file__).resolve().parents[2]


class ClockTest(unittest.TestCase):
    def test_time_command_sets_both_clocks_and_preserves_recorder_on_failure(self):
        source = (ROOT/'applications/clip/src/at_commands.c').read_text()
        handler = source[source.index('static int cmd_time_handler'):source.index('/* MODE Command Handler')]
        code = r'''
#define CONFIG_CLIP_HTTPS_POC 1
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <errno.h>
#define AT_CMD_TYPE_SET 1
#define AT_CMD_TYPE_EXEC 2
struct at_cmd_ctx {int type;const char*args;};
struct recorder_clock {uint16_t year;uint8_t month,day,hour,min,sec;uint64_t base_uptime_ms;bool valid;};
struct clip_context {struct recorder_clock time;};
static struct clip_context context;
static int error,saves,calls;
static int64_t timestamp;
static struct clip_context*clip_get_context(void){return &context;}
static uint64_t k_uptime_get(void){return 123;}
static int https_poc_set_time(int64_t n){calls++;if(error)return error;timestamp=n;return 0;}
static void config_set_time_ymd(uint16_t y,uint8_t m,uint8_t d,uint8_t h,uint8_t n,uint8_t s){assert(y==context.time.year&&m==context.time.month&&d==context.time.day&&h==context.time.hour&&n==context.time.min&&s==context.time.sec);saves++;}
static bool clip_get_current_time(uint16_t*y,uint8_t*m,uint8_t*d,uint8_t*h,uint8_t*n,uint8_t*s){*y=context.time.year;*m=context.time.month;*d=context.time.day;*h=context.time.hour;*n=context.time.min;*s=context.time.sec;return context.time.valid;}
static int create_json_response(bool ok,const char*message,const char*data,char*out,size_t size){(void)message;return snprintf(out,size,"{\"ok\":%s,\"data\":%s}",ok?"true":"false",data?data:"null");}
'''
        code += handler
        code += r'''
int main(void){
 char response[256];struct at_cmd_ctx request={1,"1800000000"};
 assert(cmd_time_handler(&request,response,sizeof(response))>0&&strstr(response,"true"));
 assert(timestamp==1800000000&&calls==1&&saves==1&&context.time.valid);
 struct recorder_clock before=context.time;
 error=-EIO;request.args="1800000060";cmd_time_handler(&request,response,sizeof(response));
 assert(strstr(response,"false")&&!memcmp(&before,&context.time,sizeof(before))&&saves==1&&calls==2);
 request.args="invalid";cmd_time_handler(&request,response,sizeof(response));assert(calls==2&&saves==1);
 request.type=3;request.args=NULL;cmd_time_handler(&request,response,sizeof(response));assert(strstr(response,"Z\""));
 return 0;
}
'''
        compile_run(code)
