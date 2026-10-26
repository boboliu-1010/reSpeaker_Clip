"""Handshake failures must keep errno categories and release transport resources."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_dtls_uploader_c import SHIM

ROOT = Path(__file__).resolve().parents[3]


class HandshakeErrorTest(unittest.TestCase):
    def test_actual_open_classifies_failures_and_always_cleans_up(self):
        shim = SHIM.replace('#define k_calloc calloc', '''
static int allocations;
static void *tracked_calloc(size_t n,size_t size){void*p=calloc(n,size);if(p)allocations++;return p;}
static void tracked_free(void*p){if(p)allocations--;free(p);}
#define k_calloc tracked_calloc''').replace('#define k_free free', '#define k_free tracked_free')
        shim = shim.replace('static int mbedtls_ssl_handshake(mbedtls_ssl_context*s){return 0;}',
                            'static int injected_error;static unsigned injected_verify;\nstatic int mbedtls_ssl_handshake(mbedtls_ssl_context*s){return injected_error;}')
        shim = shim.replace('static unsigned mbedtls_ssl_get_verify_result(mbedtls_ssl_context*s){return 0;}',
                            'static unsigned mbedtls_ssl_get_verify_result(mbedtls_ssl_context*s){return injected_verify;}')
        source = (ROOT/'applications/clip/src/dtls_upload.c').read_text()
        source = '\n'.join(line for line in source.splitlines() if not line.startswith('#include'))
        main = r'''
static int check(void){return 0;}
int main(void){
 struct {int error,expected;unsigned verify;} cases[]={
  {MBEDTLS_ERR_SSL_TIMEOUT,-ETIMEDOUT,0},
  {MBEDTLS_ERR_X509_CERT_VERIFY_FAILED,-EACCES,0},
  {MBEDTLS_ERR_NET_SEND_FAILED,-EIO,0},
  {MBEDTLS_ERR_NET_RECV_FAILED,-EIO,0},
  {MBEDTLS_ERR_SSL_INTERNAL_ERROR,-EIO,0},
  {MBEDTLS_ERR_SSL_ALLOC_FAILED,-ENOMEM,0},
  {MBEDTLS_ERR_SSL_BAD_INPUT_DATA,-EINVAL,0},
  {MBEDTLS_ERR_SSL_INVALID_RECORD,-EPROTO,0},
  {MBEDTLS_ERR_SSL_UNEXPECTED_MESSAGE,-EPROTO,0},
  {MBEDTLS_ERR_SSL_PEER_CLOSE_NOTIFY,-ECONNRESET,0},
  {-999,-EIO,0},{0,-EACCES,1},{0,0,0}
 };
 for(unsigned i=0;i<sizeof(cases)/sizeof(cases[0]);i++){
  injected_error=cases[i].error;injected_verify=cases[i].verify;
  struct dtls_upload *connection=(void*)1;
  int ret=dtls_upload_open(&connection,"127.0.0.1","9",(const unsigned char*)"CA",3,check);
  assert(ret==cases[i].expected);
  if(ret){assert(!connection&&!allocations);}else{assert(connection&&allocations==1);dtls_upload_close(connection);assert(!allocations);}
 }
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'test.c').write_text(shim+'\n#include "upload_perf.h"\n'+source+main)
            subprocess.run(['clang','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',
                            '-fsanitize=address,undefined','-I',str(ROOT/'applications/clip/include'),
                            str(root/'test.c'),str(ROOT/'applications/clip/src/upload_window.c'),
                            '-o',str(root/'test')],check=True)
            subprocess.run([str(root/'test')],check=True)
