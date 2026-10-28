"""Real Boa HTTP + production Web binding modules, with a simulated BLE byte link."""
import hashlib
import json
import queue
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest
import uvicorn

ROOT = Path(__file__).resolve().parents[3]
from server.boa.boa_app import BoaService
from server.boa.device_configurations import DeviceConfigurations
from server.boa.tests.test_service import clip_transfer

UID = '00112233445566778899aabbccddeeff'


def test_web_binding_modules_over_real_http_preserve_state_and_revoke(tmp_path):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for production Web module HTTP integration')
    service = BoaService(tmp_path)
    registry = service.registry
    registry.add_user('alice', 'a' * 40)
    registry.add_user('bob', 'b' * 40)
    registry.add_device('clip01', 'alice', 'd' * 40)
    profiles = DeviceConfigurations(registry)
    profiles.register('clip01', 'Same Clip Name', 'first-target.invalid:9528', 'd' * 40, uid=UID)
    clip_transfer(registry, body=b'fixture-existing-cloud-recording')
    original = registry.device_for_token('clip01', 'd' * 40)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0))
    listener.listen(16)
    url = 'http://127.0.0.1:' + str(listener.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(service.api, log_level='critical', access_log=False,
                                         lifespan='on', timeout_graceful_shutdown=2))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    process = None
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started, 'Loopback fixture HTTP server did not start'
        process = subprocess.Popen(
            [node, str(ROOT / 'server/web/tests/fixtures/binding-http.mjs')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=ROOT,
        )
        # Only test credentials cross stdin; never command arguments or test output.
        process.stdin.write(json.dumps(dict(url=url, uid=UID, alice='a' * 40, bob='b' * 40,
            recording_sha256=hashlib.sha256(b'fixture-existing-cloud-recording').hexdigest())) + '\n')
        process.stdin.flush()
        events = queue.Queue()

        def collect_events():
            for line in process.stdout:
                events.put(line)
            events.put(None)

        reader = threading.Thread(target=collect_events, daemon=True)
        reader.start()

        def event():
            line = events.get(timeout=15)
            assert line is not None, 'Web HTTP fixture exited before its checkpoint'
            value = json.loads(line)
            # The fixture protocol carries only non-secret phase/results.
            assert 'device_token' not in value
            return value

        assert event() == dict(phase='configured', revision=1, busy_retries=1)
        # Update the real private source while the same Node/BLE fixture remains connected.
        profiles.register('clip01', 'Same Clip Name', 'second-target.invalid:9528', 'd' * 40, uid=UID)
        process.stdin.write(json.dumps(dict(phase='reapply')) + '\n')
        process.stdin.flush()
        assert event() == dict(phase='done', revision=2, successful_writes=2,
                               clear_verified=True, cleanup_pending=True,
                               cloud_recording_hash_matches=True)
        assert process.wait(timeout=5) == 0, 'Web HTTP fixture failed'
        reader.join(timeout=2)
        assert registry.device_for_token('clip01', 'd' * 40) is None
        with pytest.raises(ValueError, match='cleanup'):
            registry.add_device('clip01', 'bob', 'e' * 40)
        with registry.db() as db:
            binding = db.execute('SELECT * FROM bindings WHERE id=?', (original['id'],)).fetchone()
            assert binding['epoch'] == 1 and binding['owner'] == 'alice' and binding['active'] == 0
        assert len(registry.clip_files('alice')) == 1
        assert registry.clip_files('bob') == []
    finally:
        if process:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        assert not thread.is_alive(), 'Loopback fixture HTTP server did not stop'
