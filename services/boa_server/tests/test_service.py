import hashlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [
    str(ROOT / "services/boa_server"),
    str(ROOT / "services/audio_storage"),
    str(ROOT / "tools/https_poc"),
]
from boa_app import create_app
from dtls_upload_protocol import COMPLETE, DATA, OPEN, frame, open_body, unpack
from receiver import OwnedSession
from registry import Registry
from resume_store import ResumeError

A = "a" * 40
B = "b" * 40
D = "d" * 40


@pytest.fixture
def setup(tmp_path):
    registry = Registry(tmp_path)
    registry.add_user("alice", A)
    registry.add_user("bob", B)
    registry.add_device("clip01", "alice", D)
    with TestClient(create_app(tmp_path)) as client:
        yield registry, client


def auth(token=A):
    return {"Authorization": f"Bearer {token}"}


def upload(client, token=A, content=b"RIFF-test-audio"):
    sha = hashlib.sha256(content).hexdigest()
    response = client.post(
        "/api/audio/uploads",
        headers=auth(token),
        json={
            "filename": "test.wav",
            "size": len(content),
            "sha256": sha,
            "mime": "audio/wav",
        },
    )
    assert response.status_code == 201, response.text
    uid = response.json()["id"]
    assert (
        client.put(
            f"/api/audio/uploads/{uid}/parts/0",
            headers={**auth(token), "X-Content-SHA256": sha},
            content=content,
        ).status_code
        == 200
    )
    assert client.post(
        f"/api/audio/uploads/{uid}/complete", headers=auth(token)
    ).status_code in (200, 202)
    assert (
        client.get(f"/api/audio/uploads/{uid}", headers=auth(token)).json()["state"]
        == "complete"
    )
    return uid


def test_app_upload_visibility_and_every_legacy_action_is_isolated(setup):
    registry, client = setup
    uid = upload(client)
    rows = client.get("/api/boa/v1/audio-files", headers=auth()).json()["items"]
    assert len(rows) == 1 and rows[0]["id"] == uid and rows[0]["source"] == "app_upload"
    assert client.get("/api/boa/v1/audio-files", headers=auth(B)).json() == {
        "items": []
    }
    assert client.get("/api/audio/recordings", headers=auth(B)).json() == {"items": []}
    for method, suffix in [
        ("GET", f"uploads/{uid}"),
        ("DELETE", f"uploads/{uid}"),
        ("POST", f"uploads/{uid}/complete"),
        ("PUT", f"uploads/{uid}/parts/0"),
        ("GET", f"recordings/{uid}"),
        ("GET", f"recordings/{uid}/content"),
        ("HEAD", f"recordings/{uid}/content"),
    ]:
        response = client.request(
            method, "/api/audio/" + suffix, headers={**auth(B), "Range": "bytes=0-3"}
        )
        assert response.status_code == 404, (method, suffix, response.status_code)
    r = client.get(
        f"/api/audio/recordings/{uid}/content", headers={**auth(), "Range": "bytes=0-3"}
    )
    assert r.status_code == 206 and r.content == b"RIFF"
    assert registry.user_for_token("invalid") is None


def clip_transfer(registry, body=b"raw-opus-frames", token=D):
    session = OwnedSession(registry)
    digest = hashlib.sha256(body).digest()
    packet = frame(
        OPEN,
        0,
        b"nonce001",
        open_body("clip01", "20261026090000", 1, len(body), digest, token),
    )
    session.feed(packet)
    responses = session.feed(frame(DATA, 0, b"nonce001", body))
    assert unpack(responses[-1])[0] == COMPLETE
    session.close()


def test_clip_complete_duplicate_restart_and_owner_content(setup, tmp_path):
    registry, client = setup
    clip_transfer(registry)
    clip_transfer(registry)
    rows = client.get("/api/boa/v1/audio-files", headers=auth()).json()["items"]
    assert len(rows) == 1 and rows[0]["source"] == "clip_direct"
    fid = rows[0]["id"]
    path = f"/api/boa/v1/audio-files/{fid}/content"
    assert client.get(path, headers=auth()).content == b"raw-opus-frames"
    assert client.head(path, headers=auth()).headers["content-length"] == "15"
    assert client.get(path, headers={**auth(), "Range": "bytes=0-2"}).content == b"raw"
    assert client.get(path, headers=auth(B)).status_code == 404
    assert client.head(path, headers=auth(B)).status_code == 404
    with TestClient(create_app(tmp_path)) as restarted:
        assert (
            restarted.get("/api/boa/v1/audio-files", headers=auth()).json()["items"][0][
                "id"
            ]
            == fid
        )


def test_unverified_and_bad_credentials_do_not_publish(setup):
    registry, client = setup
    for token in ("x" * 40,):
        with pytest.raises(ResumeError):
            clip_transfer(registry, token=token)
    session = OwnedSession(registry)
    session.feed(
        frame(
            OPEN,
            0,
            b"nonce001",
            open_body(
                "clip01",
                "20261026090000",
                1,
                100,
                hashlib.sha256(b"a" * 100).digest(),
                D,
            ),
        )
    )
    with pytest.raises(ResumeError):
        session.feed(frame(DATA, 0, b"nonce001", b"b" * 100))
    assert client.get("/api/boa/v1/audio-files", headers=auth()).json()["items"] == []
    session.close()
    for path in ("/api/audio/recordings", "/api/boa/v1/audio-files"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers=auth("invalid")).status_code == 401
    assert (
        client.get("/api/boa/v1/audio-files?limit=101", headers=auth()).status_code
        == 422
    )


def test_device_rebind_has_new_namespace_and_keeps_old_owner(setup):
    registry, client = setup
    clip_transfer(registry)
    registry.revoke_device("clip01")
    registry.add_device("clip01", "bob", "e" * 40)
    clip_transfer(registry, body=b"new-owner-file", token="e" * 40)
    a = client.get("/api/boa/v1/audio-files", headers=auth()).json()["items"]
    b = client.get("/api/boa/v1/audio-files", headers=auth(B)).json()["items"]
    assert len(a) == len(b) == 1 and a[0]["id"] != b[0]["id"]
    with pytest.raises(ResumeError):
        clip_transfer(registry)


def test_index_reconciles_file_committed_before_index_update(setup):
    registry, client = setup
    clip_transfer(registry)
    with registry.db() as db:
        db.execute("UPDATE sources SET state='receiving'")
    assert (
        len(client.get("/api/boa/v1/audio-files", headers=auth()).json()["items"]) == 1
    )
