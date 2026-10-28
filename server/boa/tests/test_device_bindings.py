"""UID delivery, client evidence, revocation and developer cleanup boundaries."""
import json
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from server.boa.boa_app import create_app
from server.boa.device_configurations import ConfigurationUnavailable, DeviceConfigurations
from server.boa.registry import Registry

UID = '00112233445566778899aabbccddeeff'
OTHER_UID = '112233445566778899aabbccddeeff00'
BASE = '/api/boa/v1/devices'
A = {'Authorization': 'Bearer ' + 'a' * 40}
B = {'Authorization': 'Bearer ' + 'b' * 40}


@pytest.fixture
def setup(tmp_path):
    registry = Registry(tmp_path)
    registry.add_user('alice', 'a' * 40)
    registry.add_user('bob', 'b' * 40)
    registry.add_device('clip01', 'alice', 'd' * 40)
    profiles = DeviceConfigurations(registry)
    with TestClient(create_app(tmp_path, allow_id_login=True), base_url='https://testserver') as client:
        yield registry, profiles, client


def enroll(profiles, endpoint='host:9528', uid=UID):
    profiles.register('clip01', 'Clip C7BB', endpoint, 'd' * 40, uid=uid)


def prepare(client, headers=A, uid=UID):
    return client.post(BASE + '/clip01/binding', json={'device_uid': uid}, headers=headers)


def test_uid_profile_preserves_original_binding_and_idempotent_revision(setup):
    registry, profiles, client = setup
    before = registry.device_for_token('clip01', 'd' * 40)
    enroll(profiles)
    first = prepare(client)
    assert first.status_code == 200
    assert first.headers['cache-control'] == 'no-store'
    assert first.json() == dict(device_id='clip01', device_uid=UID, device_name='Clip C7BB',
        binding_id=before['id'], owner_id='alice', epoch=1, revision=1,
        endpoint='host:9528', device_token='d' * 40, state='assigned')
    enroll(profiles)
    assert prepare(client).json() == first.json()
    enroll(profiles, endpoint='new-host:9528')
    assert prepare(client).json()['revision'] == 2
    assert registry.device_for_token('clip01', 'd' * 40) == before


def test_uid_is_explicit_pinned_and_not_inferred_from_name(setup):
    registry, profiles, client = setup
    profiles.register('clip01', 'Clip C7BB', 'host:9528', 'd' * 40)
    assert prepare(client).status_code == 409
    enroll(profiles)
    with pytest.raises(ValueError):
        enroll(profiles, uid=OTHER_UID)
    registry.add_device('clip02', 'alice', 'e' * 40)
    with pytest.raises(ValueError):
        profiles.register('clip02', 'Other Clip', 'host:9528', 'e' * 40, uid=UID)
    assert prepare(client).json()['device_uid'] == UID


def test_own_list_no_tokens_other_owner_and_uid_mismatch(setup, caplog):
    _, profiles, client = setup
    enroll(profiles)
    rows = client.get(BASE, headers=A)
    assert rows.status_code == 200
    row = rows.json()['items'][0]
    assert row['device_uid'] == UID and row['provisioning_state'] == 'assigned'
    assert row['last_received_at'] is None and row['last_upload_revision'] is None
    assert row['device_cleanup_pending'] is False
    assert 'device_token' not in row
    assert client.get(BASE, headers=B).json() == {'items': []}
    assert client.get(BASE).status_code == 401
    assert prepare(client, B).status_code == 404
    assert prepare(client, uid=OTHER_UID).status_code == 409
    assert client.post(BASE + '/clip01/binding', headers=B,
        json={'device_uid': UID, 'owner_id': 'alice'}).status_code == 422
    assert 'd' * 40 not in caplog.text


def test_confirm_is_client_evidence_only_and_fences_stale_revision(setup):
    _, profiles, client = setup
    enroll(profiles)
    p = prepare(client).json()
    body = dict(device_uid=UID, binding_id=p['binding_id'], revision=1, saved=True)
    path = BASE + '/clip01/binding/confirm'
    assert client.post(path, json=body, headers=B).status_code == 404
    assert client.post(path, json={**body, 'binding_id': '0' * 32}, headers=A).status_code == 409
    assert client.post(path, json={**body, 'saved': False}, headers=A).status_code == 422
    for _ in range(2):
        response = client.post(path, json=body, headers=A)
        assert response.status_code == 200
        assert response.json() == dict(state='provisioned', binding_id=p['binding_id'], revision=1)
    row = client.get(BASE, headers=A).json()['items'][0]
    assert row['provisioning_state'] == 'provisioned'
    assert row['last_received_at'] is None and row['last_upload_revision'] is None
    enroll(profiles, endpoint='new-host:9528')
    assert client.post(path, json=body, headers=A).status_code == 409
    assert client.get(BASE, headers=A).json()['items'][0]['provisioning_state'] == 'assigned'


def test_cookie_switch_fences_every_binding_mutation(setup):
    _, profiles, client = setup
    enroll(profiles)
    origin = {'Origin': 'https://testserver', 'X-Boa-User': 'alice'}
    assert client.post('/api/boa/v1/session', json={'user_id': 'alice'}, headers=origin).status_code == 200
    p = prepare(client, origin).json()
    switched = {**origin, 'X-Boa-User': 'bob'}
    assert client.get(BASE, headers=switched).status_code == 409
    assert prepare(client, switched).status_code == 409
    assert client.post(BASE + '/clip01/binding/confirm', headers=switched,
        json=dict(device_uid=UID, binding_id=p['binding_id'], revision=1, saved=True)).status_code == 409
    assert client.delete(BASE + '/clip01/binding', headers=switched).status_code == 409
    assert prepare(client, origin).status_code == 200


def test_revoke_blocks_credentials_and_developer_handoff_until_cleanup(setup):
    registry, profiles, client = setup
    enroll(profiles)
    old = prepare(client).json()
    assert client.delete(BASE + '/clip01/binding', headers=B).status_code == 404
    for _ in range(2):
        response = client.delete(BASE + '/clip01/binding', headers=A)
        assert response.json() == dict(state='revoked', device_cleanup_pending=True)
    assert registry.device_for_token('clip01', 'd' * 40) is None
    assert prepare(client).status_code == 409
    assert client.get(BASE, headers=A).json()['items'][0]['provisioning_state'] == 'revoked'
    with pytest.raises(ValueError):
        registry.add_device('clip01', 'bob', 'e' * 40)
    with pytest.raises(ValueError):
        registry.complete_device_cleanup('clip01', UID, '0' * 32)
    registry.complete_device_cleanup('clip01', UID, old['binding_id'])
    registry.add_device('clip01', 'bob', 'e' * 40)
    profiles.register('clip01', 'Other Clip', 'host:9528', 'e' * 40, uid=UID)
    assert prepare(client).status_code == 404
    new = prepare(client, B).json()
    assert new['epoch'] == 2 and new['binding_id'] != old['binding_id']
    assert new['revision'] == 1


def test_private_duplicate_source_fails_closed_without_repairing_on_import(setup):
    _, profiles, client = setup
    enroll(profiles)
    rows = json.loads(profiles.path.read_text())
    profiles.path.write_text(json.dumps(rows + rows))
    before = profiles.path.read_bytes()
    assert prepare(client).status_code == 503
    assert client.get(BASE, headers=A).status_code == 503
    with pytest.raises(ConfigurationUnavailable):
        enroll(profiles)
    assert profiles.path.read_bytes() == before


def test_developer_cli_uid_enrollment_and_cleanup_are_explicit(setup, tmp_path):
    registry, _, client = setup
    token = tmp_path / 'existing.token'
    token.write_text('d' * 40)
    token.chmod(0o600)
    result = subprocess.run([sys.executable, '-m', 'server.boa.manage',
        '--data-dir', str(tmp_path), 'configure-device', 'clip01', '--name', 'Clip C7BB',
        '--endpoint', 'host:9528', '--uid', UID, '--token-file', str(token)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert 'd' * 40 not in result.stdout + result.stderr
    assert prepare(client).json()['device_uid'] == UID
    registry.revoke_device('clip01')
    with pytest.raises(ValueError):
        registry.add_device('clip01', 'bob', 'e' * 40)


def test_same_name_uid_devices_are_distinct_without_legacy_name_issuance(setup):
    registry, profiles, client = setup
    enroll(profiles)
    registry.add_device('clip02', 'alice', 'e' * 40)
    profiles.register('clip02', 'Clip C7BB', 'host:9528', 'e' * 40, uid=OTHER_UID)
    rows = client.get(BASE, headers=A).json()['items']
    assert {row['device_uid'] for row in rows} == {UID, OTHER_UID}
    response = client.post(BASE + '/clip02/binding', headers=A, json={'device_uid': OTHER_UID})
    assert response.status_code == 200 and response.json()['device_token'] == 'e' * 40
    assert client.post(BASE + '/configuration', headers=A,
                       json={'device_name': 'Clip C7BB'}).status_code == 503


def test_verified_receipt_is_binding_epoch_evidence_and_old_files_stay_owned(setup):
    from server.boa.tests.test_service import clip_transfer
    registry, profiles, client = setup
    enroll(profiles)
    clip_transfer(registry)
    row = client.get(BASE, headers=A).json()['items'][0]
    assert row['last_received_at'] is not None
    assert row['last_upload_revision'] is None and row['provisioning_state'] == 'assigned'
    enroll(profiles, endpoint='new-host:9528')
    row = client.get(BASE, headers=A).json()['items'][0]
    assert row['revision'] == 2 and row['last_received_at'] is not None
    old_binding = row['binding_id']
    assert client.delete(BASE + '/clip01/binding', headers=A).status_code == 200
    registry.complete_device_cleanup('clip01', UID, old_binding)
    registry.add_device('clip01', 'bob', 'e' * 40)
    profiles.register('clip01', 'Clip C7BB', 'host:9528', 'e' * 40, uid=UID)
    assert client.get(BASE, headers=B).json()['items'][0]['last_received_at'] is None
    alice_files = client.get('/api/boa/v1/audio-files', headers=A).json()['items']
    assert len(alice_files) == 1
    assert client.get('/api/boa/v1/audio-files', headers=B).json()['items'] == []
    assert client.get('/api/boa/v1/audio-files/' + alice_files[0]['id'] + '/content', headers=B).status_code == 404


def test_invalid_uid_boolean_revision_and_client_proof_are_rejected(setup):
    _, profiles, client = setup
    for uid in ('c7bb', '0123456789abcdef0', UID.upper(), UID + '00' * 17):
        with pytest.raises(ValueError):
            enroll(profiles, uid=uid)
    enroll(profiles)
    p = prepare(client).json()
    body = dict(device_uid=UID, binding_id=p['binding_id'], revision=1, saved=True)
    for change in ({'revision': True}, {'revision': 0}, {'revision': 4294967296},
                   {'saved': 1}, {'saved': 'true'}, {'upload_verified': True}):
        assert client.post(BASE + '/clip01/binding/confirm', headers=A, json={**body, **change}).status_code == 422


def test_repeated_revoke_does_not_relock_developer_completed_cleanup(setup):
    registry, profiles, client = setup
    enroll(profiles)
    p = prepare(client).json()
    assert client.delete(BASE + '/clip01/binding', headers=A).status_code == 200
    registry.complete_device_cleanup('clip01', UID, p['binding_id'])
    response = client.delete(BASE + '/clip01/binding', headers=A)
    assert response.json() == dict(state='revoked', device_cleanup_pending=False)
    registry.add_device('clip01', 'bob', 'e' * 40)


@pytest.mark.parametrize('change', [
    {'device_id': 'clip02', 'device_name': 'Other', 'device_uid': OTHER_UID},
    {'device_id': 'clip02', 'device_name': 'Other', 'device_uid': OTHER_UID, 'binding_id': 'f' * 32},
])
def test_source_duplicate_binding_or_credential_fails_closed(setup, change):
    _, profiles, client = setup
    enroll(profiles)
    rows = json.loads(profiles.path.read_text())
    rows.append({**rows[0], **change})
    profiles.path.write_text(json.dumps(rows))
    assert prepare(client).status_code == 503


def test_private_source_untracked_change_never_downgrades_revision(setup):
    _, profiles, client = setup
    enroll(profiles)
    rows = json.loads(profiles.path.read_text())
    rows[0]['endpoint'] = 'changed-without-import:9528'
    profiles.path.write_text(json.dumps(rows))
    assert prepare(client).status_code == 503
    enroll(profiles, endpoint='changed-without-import:9528')
    assert prepare(client).json()['revision'] == 2


def test_reimport_after_cookie_client_confirmation_preserves_evidence(setup):
    _, profiles, client = setup
    enroll(profiles)
    body = prepare(client).json()
    response = client.post(BASE + '/clip01/binding/confirm', headers=A,
        json={key: body[key] for key in ('device_uid', 'binding_id', 'revision')} | {'saved': True})
    assert response.status_code == 200
    original = profiles.path.read_bytes()
    enroll(profiles)
    assert profiles.path.read_bytes() == original
    assert prepare(client).json()['state'] == 'provisioned'


def test_legacy_revocation_cannot_handoff_until_explicit_uid_cleanup(setup):
    from server.boa.tests.test_service import clip_transfer
    registry, _, client = setup
    old = registry.device_for_token('clip01', 'd' * 40)
    clip_transfer(registry)
    registry.revoke_device('clip01')
    # No UID profile existed when the device was revoked.
    with pytest.raises(ValueError, match='cleanup'):
        registry.add_device('clip01', 'bob', 'e' * 40)
    restarted = Registry(registry.root)
    with pytest.raises(ValueError, match='cleanup'):
        restarted.add_device('clip01', 'bob', 'e' * 40)
    with pytest.raises(ValueError):
        restarted.complete_device_cleanup('clip01', 'c7bb', old['id'])
    restarted.complete_device_cleanup('clip01', UID, old['id'])
    restarted.add_device('clip01', 'bob', 'e' * 40)
    profiles = DeviceConfigurations(restarted)
    with pytest.raises(ValueError):
        profiles.register('clip01', 'Other Clip', 'host:9528', 'e' * 40, uid=OTHER_UID)
    profiles.register('clip01', 'Other Clip', 'host:9528', 'e' * 40, uid=UID)
    assert prepare(client, B).json()['epoch'] == 2
    assert len(client.get('/api/boa/v1/audio-files', headers=A).json()['items']) == 1
    assert client.get('/api/boa/v1/audio-files', headers=B).json()['items'] == []


def test_api_revoke_unenrolled_device_has_durable_cleanup_lock(setup):
    registry, _, client = setup
    old = registry.device_for_token('clip01', 'd' * 40)
    for _ in range(2):
        response = client.delete(BASE + '/clip01/binding', headers=A)
        assert response.json() == dict(state='revoked', device_cleanup_pending=True)
    assert client.get(BASE, headers=A).json()['items'][0]['device_cleanup_pending'] is True
    with pytest.raises(ValueError, match='cleanup'):
        Registry(registry.root).add_device('clip01', 'bob', 'e' * 40)
    registry.complete_device_cleanup('clip01', UID, old['id'])
    row = client.get(BASE, headers=A).json()['items'][0]
    assert row['device_cleanup_pending'] is False and row['device_uid'] == UID
    assert client.delete(BASE + '/clip01/binding', headers=A).json()['device_cleanup_pending'] is False
    registry.add_device('clip01', 'bob', 'e' * 40)


def test_migration_locks_historical_revoked_bindings_without_reassignment(setup):
    registry, _, _ = setup
    old = registry.device_for_token('clip01', 'd' * 40)
    # Simulate a pre-feature database: revoked bindings existed without cleanup records.
    with registry.db() as db:
        db.execute("UPDATE bindings SET active=0 WHERE id=?", (old['id'],))
    restarted = Registry(registry.root)
    with pytest.raises(ValueError, match='cleanup'):
        restarted.add_device('clip01', 'bob', 'e' * 40)
    restarted.complete_device_cleanup('clip01', UID, old['id'])
    restarted.add_device('clip01', 'bob', 'e' * 40)
    assert restarted.device_for_token('clip01', 'e' * 40)['epoch'] == 2
