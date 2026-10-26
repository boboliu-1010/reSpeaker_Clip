"""Real DTLS handshake/resume and business file visibility, without hardware."""

import hashlib
import select
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [
    str(ROOT / "services/boa_server"),
    str(ROOT / "services/audio_storage"),
    str(ROOT / "tools/https_poc"),
]
import test_dtls_receiver as helpers
from boa_app import create_app
from dtls_server_transport import make_context
from dtls_upload_protocol import COMPLETE, DATA, OPEN, QUERY, frame, open_body, unpack
from make_credentials import generate
from receiver import BoaReceiver
from registry import Registry


class UnifiedDTLSTest(unittest.TestCase):
    client = helpers.RealDTLSReconnectTest.client
    request = helpers.RealDTLSReconnectTest.request

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        cert, _key = generate(self.root / "private")
        (self.root / "private/server-chain.pem").write_bytes(cert.read_bytes())
        self.cert = cert
        self.token = "x" * 40
        self.body = bytes(n % 251 for n in range(70 * 1024 + 13))
        self.sha = hashlib.sha256(self.body).digest()
        self.open = open_body(
            "clip", "20261023000000", 1, len(self.body), self.sha, self.token
        )
        self.registry = Registry(self.root / "data")
        self.registry.add_user("alice", "a" * 40)
        self.registry.add_device("clip", "alice", self.token)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.setblocking(False)
        self.receiver = BoaReceiver(self.sock, make_context(self.root), self.registry)
        self.done = threading.Event()
        self.clients = []

        def dispatch():
            while not self.done.is_set():
                if select.select([self.sock], [], [], 0.02)[0]:
                    packet, peer = self.sock.recvfrom(65535)
                    self.receiver.dispatch(packet, peer)

        self.thread = threading.Thread(target=dispatch, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.done.set()
        self.thread.join(2)
        self.receiver.close()
        for channel in self.clients:
            channel.sock.close()
        self.sock.close()
        self.tmp.cleanup()

    def test_dtls_reconnect_complete_visible_and_content_verified(self):
        a = self.client()
        self.request(a, OPEN, body=self.open)
        a.write(frame(DATA, 0, b"request1", self.body[:1024]))
        response = self.request(a, QUERY)
        while response[1] < 1024:
            response = unpack(a.read(3))
        b = self.client()
        response = self.request(b, OPEN, body=self.open, cid=b"request2")
        self.assertEqual(response[1], 1024)
        for offset in range(1024, len(self.body), 1024):
            b.write(frame(DATA, offset, b"request2", self.body[offset : offset + 1024]))
        deadline = time.monotonic() + 10
        while unpack(b.read(3))[0] != COMPLETE:
            self.assertLess(time.monotonic(), deadline)
        with TestClient(create_app(self.root / "data")) as api:
            headers = {"Authorization": "Bearer " + "a" * 40}
            rows = api.get("/api/boa/v1/audio-files", headers=headers).json()["items"]
            self.assertEqual(len(rows), 1)
            raw = api.get(
                "/api/boa/v1/audio-files/" + rows[0]["id"] + "/content", headers=headers
            )
            self.assertEqual(hashlib.sha256(raw.content).digest(), self.sha)
