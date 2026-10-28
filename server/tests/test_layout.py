import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def run_from_elsewhere(tmp_path, *arguments):
    return subprocess.run([sys.executable, *arguments], cwd=tmp_path,
                          env={**os.environ, 'PYTHONPATH': str(ROOT)},
                          capture_output=True, text=True, timeout=15)


def test_server_modules_import_without_nested_sys_path_injection(tmp_path):
    result = run_from_elsewhere(tmp_path, '-c', '''
import sys
before = list(sys.path)
from server.boa.boa_app import create_app
from server.storage.app import parse_range
from server.boa.registry import Registry
assert callable(create_app) and callable(parse_range) and callable(Registry)
assert before == sys.path
''')
    assert result.returncode == 0, result.stderr


def test_one_server_cli_and_developer_manage_entry(tmp_path):
    main = run_from_elsewhere(tmp_path, '-m', 'server', '--help')
    assert main.returncode == 0, main.stderr
    assert '--web-port' in main.stdout and '--allow-id-login' in main.stdout
    manage = run_from_elsewhere(tmp_path, '-m', 'server.boa.manage', '--help')
    assert manage.returncode == 0, manage.stderr
    assert 'configure-device' in manage.stdout


def test_frontend_and_business_have_one_source_location():
    assert (ROOT / 'server/web/index.html').is_file()
    assert (ROOT / 'server/boa/boa_app.py').is_file()
    assert (ROOT / 'server/storage/app.py').is_file()
    assert not (ROOT / 'web/firmware').exists()
    assert not (ROOT / 'services/boa_server').exists()
    assert not (ROOT / 'services/audio_storage').exists()


def test_roger_receiver_module_remains_available(tmp_path):
    result = run_from_elsewhere(tmp_path, '-m', 'server.dtls_upload_server', '--help')
    assert result.returncode == 0, result.stderr
    assert '--identities' in result.stdout
