import hashlib
import struct

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa, utils
from fastapi.testclient import TestClient

from server.boa.boa_app import create_app
from server.boa.registry import Registry

API = "/api/boa/experimental/firmware"
A, B, DEV = "a" * 40, "b" * 40, "d" * 40


def auth(token=A):
    return {"Authorization": "Bearer " + token}


def image(key):
    header = struct.pack("<IIHHIIBBHII", 0x96F3B83D, 0, 256, 0, 1024, 0, 0, 1, 5, 1, 0)
    body = header.ljust(256, b"\0") + bytes(range(256)) * 4
    digest = hashlib.sha256(body).digest()
    if isinstance(key, rsa.RSAPrivateKey):
        signature = key.sign(digest, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
                             utils.Prehashed(hashes.SHA256()))
        signature_type = 0x20
    else:
        signature = key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        signature_type = 0x22
    entries = struct.pack("<HH", 0x10, 32) + digest + struct.pack("<HH", signature_type, len(signature)) + signature
    return body + struct.pack("<HH", 0x6907, len(entries) + 4) + entries


@pytest.fixture
def setup(tmp_path):
    registry = Registry(tmp_path)
    registry.add_user("alice", A)
    registry.add_user("bob", B)
    registry.add_user("developer", DEV)
    registry.set_role("developer", "developer")
    key = ec.generate_private_key(ec.SECP256R1())
    directory = tmp_path / "firmware"
    directory.mkdir(exist_ok=True)
    (directory / "trusted-key.pem").write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    with TestClient(create_app(tmp_path)) as client:
        yield registry, client, image(key)


def import_image(client, data, profile="ble-standard"):
    return client.post(API + "/releases", params={"filename": "app.signed.bin", "profile_id": profile},
                       headers={**auth(DEV), "Content-Type": "application/octet-stream"}, content=bytes(data))


def published(client, data, profile="ble-standard"):
    result = import_image(client, data, profile)
    assert result.status_code == 201, result.text
    row = result.json()
    response = client.post(API + f"/releases/{row['id']}/publish", headers=auth(DEV))
    assert response.status_code == 200, response.text
    return response.json()


def test_web_api_requires_authentication(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get(API + "/capabilities").status_code == 401


def test_web_player_csp_allows_only_same_origin_and_blob_media(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        response = client.get('/firmware/')
        assert response.status_code == 200
        csp = response.headers['content-security-policy']
        assert "media-src 'self' blob:" in csp
        assert "connect-src 'self'" in csp
        assert "connect-src 'self';" in csp
        assert "19529" not in csp
        assert "script-src 'self'" in csp
        assert 'unsafe-inline' not in csp and 'unsafe-eval' not in csp

def test_web_wifi_configuration_does_not_depend_on_desktop_scan(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        page = client.get('/firmware/').text
        assert 'id="scan-wifi"' not in page
        assert 'id="wifi-networks"' not in page
        assert 'id="clip-ssid"' in page
        assert 'id="toggle-wifi-password"' in page
        assert 'id="save-wifi"' in page


def test_only_developer_can_import_publish_and_assign_roles(setup):
    registry, client, data = setup
    assert client.get(API + "/capabilities", headers=auth()).json()["role"] == "user"
    assert client.post(API + "/releases", headers=auth(), content=data).status_code == 403
    assert registry.role("alice") == "user"
    with pytest.raises(ValueError):
        registry.set_role("alice", "admin")
    with pytest.raises(ValueError):
        registry.set_role("missing", "developer")
    assert client.post(API + "/set-role", headers=auth(), json={"role": "developer"}).status_code == 404


def test_signed_image_publish_download_range_withdraw_and_restart(setup, tmp_path):
    _, client, data = setup
    row = import_image(client, data).json()
    assert row["verification"] == "trusted" and row["version"] == "0.1.5+1"
    assert client.get(API + "/releases", headers=auth()).json()["items"] == []
    path = API + f"/releases/{row['id']}/content"
    assert client.get(path, headers=auth()).status_code == 404
    assert client.post(API + f"/releases/{row['id']}/publish", headers=auth()).status_code == 403
    assert client.post(API + f"/releases/{row['id']}/publish", headers=auth(DEV)).status_code == 200
    response = client.get(path, headers=auth())
    assert response.content == data
    assert response.headers["etag"] == '"' + hashlib.sha256(data).hexdigest() + '"'
    assert client.get(path, headers={**auth(), "Range": "bytes=2-8"}).content == data[2:9]
    with TestClient(create_app(tmp_path)) as restarted:
        assert len(restarted.get(API + "/releases", headers=auth(B)).json()["items"]) == 1
    assert client.post(API + f"/releases/{row['id']}/withdraw", headers=auth(DEV)).status_code == 200
    assert client.get(path, headers=auth()).status_code == 410
    assert client.post(API + f"/releases/{row['id']}/publish", headers=auth(DEV)).status_code == 409


def test_untrusted_corrupt_and_oversized_imports_fail_closed(setup):
    _, client, data = setup
    altered = bytearray(data); altered[300] ^= 1
    assert import_image(client, altered).status_code == 422
    assert import_image(client, b"not-firmware").status_code == 422
    assert import_image(client, data, "unknown").status_code == 422
    assert client.post(API + "/releases", params={"filename": "../app.bin", "profile_id": "ble-standard"},
                       headers=auth(DEV), content=data).status_code == 422
    assert client.post(API + "/releases", headers={**auth(DEV), "Content-Length": str(8 * 1024 * 1024 + 1)}, content=b"").status_code == 413
    untrusted = import_image(client, image(ec.generate_private_key(ec.SECP256R1()))).json()
    assert untrusted["verification"] == "untrusted"
    assert client.post(API + f"/releases/{untrusted['id']}/publish", headers=auth(DEV)).status_code == 409


def test_upgrade_records_are_owned_and_completion_needs_confirmed_hash(setup):
    _, client, data = setup
    row = published(client, data)
    start = client.post(API + "/upgrades", headers=auth(), json={"release_id": row["id"], "device_label": "My Clip"})
    assert start.status_code == 201
    uid = start.json()["id"]
    assert client.get(API + "/upgrades", headers=auth(B)).json()["items"] == []
    path = API + "/upgrades/" + uid
    assert client.patch(path, headers=auth(B), json={"state": "failed"}).status_code == 404
    assert client.patch(path, headers=auth(), json={"state": "succeeded"}).status_code == 409
    assert client.patch(path, headers=auth(), json={"state": "awaiting_reconnect"}).status_code == 200
    assert client.patch(path, headers=auth(), json={"state": "uploading"}).status_code == 409
    assert client.patch(path, headers=auth(), json={"state": "succeeded", "active": True, "confirmed": True, "image_hash": row["image_hash"]}).status_code == 200
    assert client.patch(path, headers=auth(), json={"state": "uploading"}).status_code == 409
    blocked = published(client, data, "dtls-upload")
    assert client.post(API + "/upgrades", headers=auth(), json={"release_id": blocked["id"], "device_label": "Clip"}).status_code == 409


def test_web_page_has_strict_headers_and_no_secret_reflection(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        response = client.get("/firmware/")
        assert response.status_code == 200
        assert "unsafe-inline" not in response.headers["content-security-policy"]
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert client.get("/firmware/smp.mjs").status_code == 200


def test_demo_mode_and_public_key_rotation_prevent_device_upgrade(setup, tmp_path):
    _, client, data = setup
    row = published(client, data)
    marker = tmp_path / "firmware/demo-only"
    marker.touch()
    assert client.post(API + "/upgrades", headers=auth(), json={"release_id": row["id"], "device_label": "Clip"}).status_code == 409
    marker.unlink()
    (tmp_path / "firmware/trusted-key.pem").unlink()
    assert client.post(API + "/upgrades", headers=auth(), json={"release_id": row["id"], "device_label": "Clip"}).status_code == 409


def test_rsa2048_mcuboot_signature_and_dtls_ota_profile(setup, tmp_path):
    _, client, _ = setup
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (tmp_path / "firmware/trusted-key.pem").write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    data = image(key)
    row = published(client, data, "boa-dtls-ota-v1")
    assert row["verification"] == "trusted"
    assert row["signature_algorithm"] == "rsa2048-pss-sha256"
    assert row["boot_mode"] == "overwrite-only"
    assert client.post(API + "/upgrades", headers=auth(), json={"release_id": row["id"], "device_label": "Clip"}).status_code == 201
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert import_image(client, image(other)).json()["verification"] == "untrusted"
    corrupt = bytearray(data)
    corrupt[-1] ^= 1
    assert import_image(client, corrupt).json()["verification"] == "untrusted"
    # A label must not enable the new DTLS OTA profile for the old ECDSA demos.
    ecdsa_data = image(ec.generate_private_key(ec.SECP256R1()))
    assert import_image(client, ecdsa_data, "boa-dtls-ota-v1").status_code == 422
