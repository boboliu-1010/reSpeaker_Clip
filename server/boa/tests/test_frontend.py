"""Web listener shares authentication, storage and lifetime with the API listener."""
import hashlib
import socket
import ssl
import subprocess
import sys
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from server.boa.boa_app import create_app
from server.boa.frontend import Frontend
from server.boa.registry import Registry

from server.make_credentials import generate

A, B = 'a' * 40, 'b' * 40


def test_frontend_shares_auth_upload_range_and_single_backend_lifetime(tmp_path):
    registry = Registry(tmp_path)
    registry.add_user('alice', A)
    registry.add_user('bob', B)
    events = []

    def listener(_registry):
        events.append('start')
        return lambda: events.append('stop')

    api = create_app(tmp_path, listener)
    with TestClient(api) as backend:
        with TestClient(Frontend(api)) as web:
            assert events == ['start']
            response = web.get('/', follow_redirects=False)
            assert response.status_code == 307
            assert response.headers['location'] == '/firmware/#recordings'
            page = web.get('/firmware/')
            assert page.status_code == 200
            assert '我的录音' in page.text
            assert "media-src 'self' blob:" in page.headers['content-security-policy']
            assert web.get('/api/boa/v1/audio-files').status_code == 401
            headers = {'Authorization': 'Bearer ' + A}
            body = b'RIFF-frontend-transport-test'
            digest = hashlib.sha256(body).hexdigest()
            response = web.post('/api/audio/uploads', headers=headers, json={
                'filename': 'front.wav', 'size': len(body), 'sha256': digest, 'mime': 'audio/wav'})
            assert response.status_code == 201
            uid = response.json()['id']
            assert web.put(f'/api/audio/uploads/{uid}/parts/0', content=body,
                           headers={**headers, 'X-Content-SHA256': digest}).status_code == 200
            assert web.post(f'/api/audio/uploads/{uid}/complete', headers=headers).status_code in (200, 202)
            assert backend.get('/api/boa/v1/audio-files', headers=headers).json()['items'][0]['id'] == uid
            path = f'/api/audio/recordings/{uid}/content'
            assert web.get(path, headers={**headers, 'Range': 'bytes=0-3'}).content == b'RIFF'
            assert web.head(path, headers=headers).headers['content-length'] == str(len(body))
            assert web.get(path, headers={'Authorization': 'Bearer ' + B}).status_code == 404
            assert web.get('/outside').status_code == 404
        assert events == ['start']
    assert events == ['start', 'stop']


def free_ports():
    with socket.socket() as first, socket.socket() as second:
        first.bind(('127.0.0.1', 0)); second.bind(('127.0.0.1', 0))
        return first.getsockname()[1], second.getsockname()[1]


@pytest.mark.parametrize('tls', [False, True])
def test_launcher_two_ports_and_graceful_shutdown(tmp_path, tls):
    api_port, web_port = free_ports()
    data = tmp_path / 'data'
    Registry(data).add_user('alice', A)
    command = [sys.executable, '-m', 'server', '--data-dir', str(data),
               '--port', str(api_port), '--web-port', str(web_port)]
    scheme = 'http'
    context = True
    if tls:
        cert, _ = generate(tmp_path/'tls/private', '127.0.0.1')
        (cert.parent/'server-chain.pem').write_bytes(cert.read_bytes())
        command += ['--tls-root', str(tmp_path/'tls')]
        scheme = 'https'
        context = ssl.create_default_context(cafile=str(cert))
    else:
        command += ['--http-only']
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        with httpx.Client(verify=context, trust_env=False, timeout=1) as client:
            web_url = f'{scheme}://127.0.0.1:{web_port}'
            for _ in range(120):
                if process.poll() is not None:
                    raise AssertionError(process.stdout.read())
                try:
                    assert client.get(web_url + '/firmware/').status_code == 200
                    break
                except httpx.ConnectError:
                    time.sleep(.05)
            else:
                raise AssertionError('Both listeners did not start')
            for port in (api_port, web_port):
                url = f'{scheme}://127.0.0.1:{port}/api/boa/v1/audio-files'
                assert client.get(url).status_code == 401
                assert client.get(url, headers={'Authorization': 'Bearer '+A}).json() == {'items': []}
            if tls:
                with pytest.raises(httpx.ConnectError, match='CERTIFICATE_VERIFY_FAILED'):
                    httpx.get(web_url, trust_env=False, timeout=1)
    finally:
        process.terminate()
        process.communicate(timeout=12)
    assert process.returncode == 0
    for port in (api_port, web_port):
        with socket.socket() as probe:
            assert probe.connect_ex(('127.0.0.1', port)) != 0


def test_launcher_rejects_colliding_ports_before_creating_data(tmp_path):
    result = subprocess.run([sys.executable, '-m', 'server',
                             '--data-dir', str(tmp_path/'absent'), '--http-only',
                             '--port', '9528', '--web-port', '9528'], capture_output=True, text=True, check=False)
    assert result.returncode == 2
    assert 'different' in result.stderr
    assert not (tmp_path/'absent').exists()


def test_web_bind_failure_stops_backend_and_releases_data_lock(tmp_path):
    api_port, _ = free_ports()
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0)); occupied.listen()
        web_port = occupied.getsockname()[1]
        result = subprocess.run([sys.executable, '-m', 'server',
                                 '--data-dir', str(tmp_path/'data'), '--http-only',
                                 '--port', str(api_port), '--web-port', str(web_port)],
                                capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode != 0
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', api_port)) != 0
    import fcntl
    with (tmp_path/'data/server.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_health_is_public_but_files_stay_private(tmp_path):
    from server.boa.boa_app import create_app
    from fastapi.testclient import TestClient
    from server.boa.frontend import Frontend

    backend = create_app(tmp_path)
    with TestClient(backend) as api, TestClient(Frontend(backend)) as web:
        for client in (api, web):
            response = client.get('/api/boa/v1/health')
            assert response.status_code == 200
            assert response.json() == {'service': 'boa', 'status': 'ok'}
            assert response.headers['cache-control'] == 'no-store'
            assert client.get('/api/boa/v1/audio-files').status_code == 401
