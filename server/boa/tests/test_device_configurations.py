import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from server.boa.boa_app import create_app
from server.boa.registry import Registry
from server.boa.device_configurations import DeviceConfigurations

PATH = '/api/boa/v1/devices/configuration'
ORIGIN = {'Origin': 'https://testserver', 'X-Boa-User': 'alice'}


@pytest.fixture
def setup(tmp_path):
    registry = Registry(tmp_path)
    registry.add_user('alice', 'a' * 40)
    registry.add_user('bob', 'b' * 40)
    registry.add_device('clip01', 'alice', 'd' * 40)
    profiles = DeviceConfigurations(registry)
    profiles.register('clip01', 'Clip C7BB', '100.58.19.213:9528', 'd' * 40)
    with TestClient(create_app(tmp_path, allow_id_login=True), base_url='https://testserver') as client:
        yield registry, profiles, client


def request(client, token='a' * 40, name='Clip C7BB', **kwargs):
    return client.post(PATH, json={'device_name': name}, headers={'Authorization': 'Bearer ' + token}, **kwargs)


def test_owned_profile_reuses_original_credential_and_binding(setup):
    registry, _, client = setup
    before = registry.device_for_token('clip01', 'd' * 40)
    response = request(client)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json() == dict(device_name='Clip C7BB', device_id='clip01', owner='alice',
                                   endpoint='100.58.19.213:9528', device_token='d' * 40)
    assert request(client).json() == response.json()
    assert registry.device_for_token('clip01', 'd' * 40) == before


def test_anonymous_other_owner_and_unknown_name_cannot_read(setup):
    _, _, client = setup
    assert client.post(PATH, json={'device_name': 'Clip C7BB'}).status_code == 401
    for token, name in [('b' * 40, 'Clip C7BB'), ('a' * 40, 'Clip other')]:
        response = request(client, token, name)
        assert response.status_code == 404
        assert 'd' * 40 not in response.text
    assert client.post(PATH, json={'device_name': 'Clip C7BB', 'owner': 'alice'},
                       headers={'Authorization': 'Bearer ' + 'b' * 40}).status_code == 422


def test_cookie_requires_origin_and_current_user(setup):
    _, _, client = setup
    assert client.post('/api/boa/v1/session', json={'user_id': 'alice'}, headers=ORIGIN).status_code == 200
    assert client.post(PATH, json={'device_name': 'Clip C7BB'}, headers=ORIGIN).status_code == 200
    assert client.post(PATH, json={'device_name': 'Clip C7BB'}, headers={**ORIGIN, 'Origin': 'https://other'}).status_code == 403
    assert client.post(PATH, json={'device_name': 'Clip C7BB'}, headers={**ORIGIN, 'X-Boa-User': 'bob'}).status_code == 409
    assert client.post(PATH, json={'device_name': 'Clip C7BB'}, headers={**ORIGIN, 'Authorization': 'Bearer invalid'}).status_code == 401


def test_revoke_rebind_does_not_reissue_old_profile(setup):
    registry, _, client = setup
    old_binding = registry.device_for_token('clip01', 'd' * 40)['id']
    registry.revoke_device('clip01')
    assert request(client).status_code == 404
    # This test models a developer-authorized, fully cleaned handoff.
    registry.complete_device_cleanup('clip01', '00112233445566778899aabbccddeeff', old_binding)
    registry.add_device('clip01', 'bob', 'e' * 40)
    assert request(client, 'b' * 40).status_code == 404
    assert request(client).status_code == 404


def test_private_file_permissions_and_corruption_fail_closed(setup):
    _, profiles, client = setup
    assert profiles.path.stat().st_mode & 0o777 == 0o600
    profiles.path.chmod(0o644)
    assert request(client).status_code == 503
    profiles.path.chmod(0o600)
    profiles.path.write_text('{bad')
    assert request(client).status_code == 503


def test_registration_rejects_wrong_token_ambiguous_alias_and_unsafe_target(setup):
    registry, profiles, client = setup
    registry.add_device('clip02', 'alice', 'e' * 40)
    for device, endpoint, token in [('clip01', 'host:9528', 'x' * 40),
                                     ('clip02', 'host:9528', 'e' * 40),
                                     ('clip01', 'https://host:9528', 'd' * 40)]:
        with pytest.raises(ValueError):
            profiles.register(device, 'Clip C7BB', endpoint, token)
    assert request(client).status_code == 200


def test_profile_symlink_is_rejected(setup, tmp_path):
    _, profiles, client = setup
    content = profiles.path.read_bytes()
    profiles.path.unlink()
    target = tmp_path / 'other.json'
    target.write_bytes(content)
    target.chmod(0o600)
    profiles.path.symlink_to(target)
    assert request(client).status_code == 503


def test_developer_cli_imports_existing_credential_without_rotating_it(setup, tmp_path):
    registry, _, client = setup
    token = tmp_path / 'existing.token'
    token.write_text('d' * 40)
    token.chmod(0o600)
    before = registry.device_for_token('clip01', 'd' * 40)
    result = subprocess.run([sys.executable, '-m', 'server.boa.manage',
                             '--data-dir', str(tmp_path), 'configure-device', 'clip01',
                             '--name', 'Clip C7BB', '--endpoint', 'new-host:9528',
                             '--token-file', str(token)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'd' * 40 not in result.stdout + result.stderr
    assert request(client).json()['endpoint'] == 'new-host:9528'
    assert registry.device_for_token('clip01', 'd' * 40) == before
