
import pytest
from fastapi.testclient import TestClient

from server.boa.boa_app import create_app
from server.boa.registry import Registry
from server.boa.tests.test_service import clip_transfer

ORIGIN = {'Origin': 'https://testserver'}
SESSION = '/api/boa/v1/session'
FILES = '/api/boa/v1/audio-files'
CAPS = '/api/boa/experimental/firmware/capabilities'


@pytest.fixture
def setup(tmp_path):
    registry = Registry(tmp_path)
    registry.add_user('alice', 'a' * 40)
    registry.add_user('bob', 'b' * 40)
    registry.add_user('dev', 'v' * 40)
    registry.set_role('dev', 'developer')
    registry.add_device('clip01', 'alice', 'd' * 40)
    app = create_app(tmp_path, allow_id_login=True)
    with TestClient(app, base_url='https://testserver') as client:
        yield registry, app, client


def login(client, user='alice'):
    response = client.post(SESSION, json={'user_id': user}, headers=ORIGIN)
    if response.status_code == 200:
        client.headers['X-Boa-User'] = user
    return response


def test_id_login_disabled_unless_explicitly_enabled(tmp_path):
    registry = Registry(tmp_path)
    registry.add_user('alice', 'a' * 40)
    with TestClient(create_app(tmp_path), base_url='https://testserver') as client:
        assert login(client).status_code == 403


def test_login_cookie_restores_identity_without_returning_a_token(setup):
    _, _, client = setup
    response = login(client)
    assert response.status_code == 200
    assert response.json() == {'user_id': 'alice', 'role': 'user'}
    cookie = response.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=strict' in cookie and 'secure' in cookie
    assert client.get(SESSION).json()['user_id'] == 'alice'
    assert client.get(CAPS).json()['user_id'] == 'alice'
    assert client.get(FILES).status_code == 200


def test_real_clip_file_remains_scoped_to_selected_user(setup):
    registry, app, alice = setup
    clip_transfer(registry, body=b'actual-clip-test-bytes')
    assert login(alice).status_code == 200
    row = alice.get(FILES).json()['items'][0]
    path = FILES + '/' + row['id'] + '/content'
    assert alice.get(path, headers={'Range': 'bytes=0-2'}).content == b'act'
    with TestClient(app, base_url='https://testserver') as bob:
        assert login(bob, 'bob').status_code == 200
        assert bob.get(FILES).json()['items'] == []
        assert bob.get(path).status_code == 404
        assert bob.head(path).status_code == 404


def test_cookie_never_grants_developer_privileges(setup):
    _, _, client = setup
    assert login(client, 'dev').status_code == 200
    assert client.get(CAPS).json()['role'] == 'user'
    assert client.post('/api/boa/experimental/firmware/releases/x/publish', headers=ORIGIN).status_code == 403
    assert client.get(CAPS, headers={'Authorization': 'Bearer ' + 'v' * 40}).json()['role'] == 'developer'


def test_unknown_invalid_and_device_ids_do_not_create_users(setup):
    _, _, client = setup
    for user in ('unknown', 'clip01'):
        assert login(client, user).status_code == 404
    for user in ('../alice', '', 'a' * 33):
        assert login(client, user).status_code == 422


def test_logout_revokes_cookie_replay_and_other_sessions_stay_independent(setup):
    _, app, client = setup
    login(client)
    stolen = client.cookies.get('boa_session')
    assert client.delete(SESSION, headers=ORIGIN).status_code == 204
    assert client.get(SESSION).status_code == 401
    with TestClient(app, base_url='https://testserver') as replay:
        assert replay.get(FILES, headers={'Cookie': 'boa_session=' + stolen}).status_code == 401


def test_expired_or_disabled_user_session_is_rejected(setup):
    registry, _, client = setup
    login(client)
    with registry.db() as db:
        db.execute('UPDATE web_sessions SET expires=0')
    assert client.get(FILES).status_code == 401
    login(client)
    with registry.db() as db:
        db.execute("UPDATE users SET active=0 WHERE id='alice'")
    assert client.get(CAPS).status_code == 401


def test_cross_origin_cookie_writes_and_bad_bearer_are_rejected(setup):
    _, _, client = setup
    assert client.post(SESSION, json={'user_id': 'alice'}, headers={'Origin': 'https://other'}).status_code == 403
    assert client.post(SESSION, json={'user_id': 'alice'}).status_code == 403
    login(client)
    assert client.delete(SESSION, headers={'Origin': 'https://other'}).status_code == 403
    assert client.post('/api/boa/experimental/firmware/upgrades', json={'release_id': 'a'*32, 'device_label': 'Clip'}, headers={'Origin': 'https://other'}).status_code == 403
    assert client.post('/api/audio/uploads', json={}, headers={'Origin': 'https://other'}).status_code == 403
    assert client.get(FILES, headers={'Authorization': 'Bearer wrong'}).status_code == 401


def test_cross_tab_account_switch_rejects_stale_identity_and_logout(setup):
    registry, _, client = setup
    clip_transfer(registry)
    login(client, 'alice')
    assert client.get(FILES).json()['items']
    # Another tab changes the shared cookie, while this tab still expects Alice.
    assert client.post(SESSION, json={'user_id': 'bob'}, headers=ORIGIN).status_code == 200
    assert client.get(FILES).status_code == 409
    assert client.get(CAPS).status_code == 409
    assert client.delete(SESSION, headers=ORIGIN).status_code == 409
    client.headers['X-Boa-User'] = 'bob'
    assert client.get(SESSION).json()['user_id'] == 'bob'
    assert client.get(FILES).json()['items'] == []


def test_session_survives_restart_but_not_disabling_mode_and_db_has_only_hash(setup):
    registry, _, client = setup
    login(client)
    cookie = client.cookies.get('boa_session')
    with registry.db() as db:
        row = db.execute('SELECT digest FROM web_sessions').fetchone()
        assert len(row['digest']) == 64 and cookie not in row['digest']
    headers = {'Cookie': 'boa_session=' + cookie, 'X-Boa-User': 'alice'}
    with TestClient(create_app(registry.root, allow_id_login=True), base_url='https://testserver') as restarted:
        assert restarted.get(FILES, headers=headers).status_code == 200
    with TestClient(create_app(registry.root), base_url='https://testserver') as disabled:
        assert disabled.get(FILES, headers=headers).status_code == 401
