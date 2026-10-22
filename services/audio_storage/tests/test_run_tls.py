"""Exercise the real launcher with a process-scoped development certificate."""

import http.client
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path

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
    root.mkdir()
    (root / "token").write_text("test-only-token")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    launcher = Path(__file__).resolve().parents[1] / "run.py"
    process = subprocess.Popen(
        [
            sys.executable,
            str(launcher),
            "--data-dir",
            str(root),
            "--port",
            str(port),
            "--ssl-certfile",
            str(cert),
            "--ssl-keyfile",
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
                client.get(url, headers={"Authorization": "Bearer test-only-token"}).status_code
                == 200
            )
        # The desktop pool retires idle sockets at 15s. The server must not
        # expire them at Uvicorn's shorter 5s default during file verification.
        connection = http.client.HTTPSConnection(
            "127.0.0.1",
            port,
            context=ssl.create_default_context(cafile=str(cert)),
            timeout=2,
        )
        try:
            connection.request("GET", "/api/audio/recordings")
            response = connection.getresponse()
            assert response.status == 401
            response.read()
            original_socket = connection.sock
            time.sleep(6)
            connection.request("GET", "/api/audio/recordings")
            response = connection.getresponse()
            assert response.status == 401
            response.read()
            assert connection.sock is original_socket
        finally:
            connection.close()
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
    launcher = Path(__file__).resolve().parents[1] / "run.py"
    result = subprocess.run(
        [
            sys.executable,
            str(launcher),
            "--data-dir",
            str(tmp_path / "data"),
            "--ssl-certfile",
            "missing.pem",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "must be provided together" in result.stderr
    assert not (tmp_path / "data").exists()
