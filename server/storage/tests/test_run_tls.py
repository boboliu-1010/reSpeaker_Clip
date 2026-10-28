"""Exercise the real launcher with a process-scoped development certificate."""

import socket
import ssl
import subprocess
import sys
import time
from server.boa.registry import Registry
from server.make_credentials import generate

import httpx


def test_launcher_tls_and_auth(tmp_path):
    cert = tmp_path / "server.pem"
    key = tmp_path / "server.key"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    root = tmp_path / "data"
    Registry(root).add_user("alice", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    dtls_cert, _ = generate(tmp_path / "tls/private", "127.0.0.1")
    (dtls_cert.parent / "server-chain.pem").write_bytes(dtls_cert.read_bytes())
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "server",
            "--data-dir",
            str(root),
            "--tls-root",
            str(tmp_path / "tls"),
            "--web-port",
            "0",
            "--port",
            str(port),
            "--https-certfile",
            str(cert),
            "--https-keyfile",
            str(key),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        url = f"https://127.0.0.1:{port}/api/audio/recordings"
        with httpx.Client(
            verify=ssl.create_default_context(cafile=str(cert)), trust_env=False, timeout=1
        ) as client:
            for _ in range(100):
                if process.poll() is not None:
                    raise AssertionError(process.stdout.read())
                try:
                    response = client.get(url)
                    break
                except httpx.ConnectError:
                    time.sleep(0.05)
            else:
                raise AssertionError("TLS listener did not start")
            assert response.status_code == 401
            assert (
                client.get(url, headers={"Authorization": "Bearer aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}).status_code
                == 200
            )
        try:
            httpx.get(url, trust_env=False, timeout=1)
        except httpx.ConnectError as error:
            assert "CERTIFICATE_VERIFY_FAILED" in str(error)
        else:
            raise AssertionError("Untrusted certificate was accepted")
    finally:
        process.terminate()
        process.communicate(timeout=10)


def test_launcher_rejects_incomplete_tls_config(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "server",
            "--data-dir",
            str(tmp_path / "data"),
            "--https-certfile",
            "missing.pem",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "must be supplied together" in result.stderr
    assert not (tmp_path / "data").exists()
