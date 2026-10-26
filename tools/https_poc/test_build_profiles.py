"""Production must remove laboratory controls without undoing DATA optimizations."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import build
from build import preset_overlays

ROOT = Path(__file__).resolve().parents[2]


class BuildProfilesTest(unittest.TestCase):
    def test_helper_selects_only_the_requested_baseline_build_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ca = root/'ca.pem'
            ca.write_text('-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----\n')
            for production in (False, True):
                argv = ['build.py', '--ncs', str(root), '--sdk', str(root),
                        '--build', str(root/('production' if production else 'default')),
                        '--ca', str(ca), '--preset', 'dtls-single']
                if production:
                    argv.append('--production')
                with patch('sys.argv', argv), patch('build.subprocess.run', return_value=SimpleNamespace(returncode=0)) as run:
                    with self.assertRaises(SystemExit) as result:
                        build.main()
                self.assertEqual(result.exception.code, 0)
                command = run.call_args.args[0]
                self.assertIn('-DSNIPPET=production' if production else '-DSNIPPET=', command)
                configs = next(x for x in command if x.startswith('-Dclip_EXTRA_CONF_FILE='))
                self.assertEqual('runtime.conf' in configs, not production)
                self.assertIn('dtls-single.conf', configs)

    def test_default_and_production_share_performance_settings(self):
        for production in (False, True):
            name = 'production' if production else 'default'
            values = {}
            for conf in ('dtls.conf', *preset_overlays('dtls-single', production)):
                for line in (ROOT/'applications/clip'/conf).read_text().splitlines():
                    if line.startswith('CONFIG_') and '=' in line:
                        key, value = line.split('=', 1)
                        values[key] = value
            self.assertNotIn('CONFIG_CLIP_DEBUG_INTERFACES', values)
            self.assertEqual(values.get('CONFIG_CLIP_WIFI_DIAG') == 'y', not production)
            for key, value in {
                'CONFIG_CLIP_DTLS_UPLOAD': 'y',
                'CONFIG_CLIP_DTLS_INITIAL_WINDOW_PACKETS': '128', 'CONFIG_CLIP_DTLS_WINDOW_PACKETS': '128',
                'CONFIG_CLIP_DTLS_READ_CACHE_BYTES': '8192', 'CONFIG_HEAP_MEM_POOL_SIZE': '81920',
                'CONFIG_PSA_USE_CC3XX_AEAD_DRIVER': 'y', 'CONFIG_NET_PKT_BUF_TX_DATA_POOL_SIZE': '24576',
                'CONFIG_CLIP_NETWORK_BACKPORT_ARP': 'y', 'CONFIG_NET_DHCPV4_INIT_REBOOT': 'n',
            }.items():
                self.assertEqual(values[key], value, (name,key))

    def test_actual_registration_excludes_debug_commands_in_production(self):
        source = (ROOT/'applications/clip/src/https_poc.c').read_text()
        registration = 'static const struct at_command commands[]'+source.split('static const struct at_command commands[]',1)[1].split('};',1)[0]+'};'
        for debug in (False, True):
            code = '''
#include <stdio.h>
#define CONFIG_CLIP_DTLS_UPLOAD 1
#define CONFIG_CLIP_UPLOAD_APP 1
#define AT_CMD_QUERY 2
#define AT_CMD_SET 1
#define AT_CMD_EXEC 4
static void command(void){}
struct at_command {const char*name;int flags;void(*handler)(void);};
'''
            if debug:
                code += '#define CONFIG_CLIP_DEBUG_INTERFACES 1\n#define CONFIG_CLIP_DTLS_PROFILE 1\n#define CONFIG_CLIP_HTTPS_PROFILE 1\n'
            code += registration+'\nint main(void){for(unsigned i=0;i<sizeof(commands)/sizeof(commands[0]);i++)printf("%s:%d\\n",commands[i].name,commands[i].flags);return 0;}\n'
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root/'test.c').write_text(code)
                subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror',str(root/'test.c'),'-o',str(root/'test')],check=True)
                output = subprocess.check_output([str(root/'test')],text=True)
            commands = dict(line.split(':') for line in output.splitlines())
            for command in ('NETCFG','NETCHECK','UPLOADCFG','UPLOADAUTO','UPLOADSTATE','UPLOADLIST','UPLOADCANCEL'):
                self.assertIn(command, commands)
            self.assertNotIn('UPTIME',commands)
            self.assertNotIn('UPLOADSAVE',commands)
            for command in ('UPLOADNET','UPLOADPERF','UPLOADCLEAR','UPLOADCLOCK'):
                self.assertEqual(command in commands, debug)
            self.assertEqual(commands['UPLOAD'], '3' if debug else '2')
