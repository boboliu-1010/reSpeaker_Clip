"""Exercise a deployed DTLS receiver and its HTTPS file list with synthetic bytes.

Credentials are read only from private files. This is transport validation,
not a hardware recording/codec validation.
"""

import argparse
import datetime
import hashlib
import ipaddress
import json
import secrets
import socket
import ssl
import time
import urllib.request
from pathlib import Path

from cryptography import x509
from server.dtls_server_transport import DatagramTLS
from server.dtls_upload_protocol import (
    COMPLETE,
    DATA,
    OPEN,
    QUERY,
    RECEIPT,
    frame,
    open_body,
    unpack,
)
from OpenSSL import SSL


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=9528)
    parser.add_argument(
        "--connect-host", help="optional route override for on-host diagnostics"
    )
    parser.add_argument("--device", required=True)
    parser.add_argument("--device-token-file", type=Path, required=True)
    parser.add_argument("--user-token-file", type=Path, required=True)
    parser.add_argument("--dtls-ca", type=Path, required=True)
    parser.add_argument("--https-ca", type=Path, required=True)
    args = parser.parse_args()
    body = bytes(index % 251 for index in range(64 * 1024 + 17))
    digest = hashlib.sha256(body).digest()
    session = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")
    nonce = secrets.token_bytes(8)
    context = SSL.Context(SSL.DTLS_CLIENT_METHOD)
    context.set_min_proto_version(0xFEFD)
    context.set_max_proto_version(0xFEFD)
    context.set_cipher_list(b"ECDHE-ECDSA-AES128-GCM-SHA256")
    context.load_verify_locations(str(args.dtls_ca))

    def verify(connection, cert, error, depth, ok):
        if not ok or depth != 0:
            return ok
        try:
            names = (
                cert.to_cryptography()
                .extensions.get_extension_for_class(x509.SubjectAlternativeName)
                .value
            )
            address = ipaddress.ip_address(args.host)
            return address in names.get_values_for_type(x509.IPAddress)
        except (ValueError, x509.ExtensionNotFound):
            return False

    context.set_verify(SSL.VERIFY_PEER, verify)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    sock.setblocking(False)
    channel = DatagramTLS(sock, (args.connect_host or args.host, args.port), context)
    channel.connection.set_connect_state()
    try:
        channel.handshake()
        channel.write(
            frame(
                OPEN,
                0,
                nonce,
                open_body(
                    args.device,
                    session,
                    1,
                    len(body),
                    digest,
                    args.device_token_file.read_text().strip(),
                ),
            )
        )
        unpack(channel.read(5))
        for offset in range(0, len(body), 8192):
            end = min(offset + 8192, len(body))
            for pos in range(offset, end, 1024):
                channel.write(frame(DATA, pos, nonce, body[pos : min(pos + 1024, end)]))
            channel.write(frame(QUERY, 0, nonce))
            deadline = time.monotonic() + 10
            while True:
                kind, durable, transfer, receipt = unpack(channel.read(5))
                if transfer == nonce and durable >= end:
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError("Durable checkpoint deadline")
        assert kind == COMPLETE and RECEIPT.unpack(receipt)[-1] == 1
    finally:
        sock.close()
    token = args.user_token_file.read_text().strip()
    https = ssl.create_default_context(cafile=str(args.https_ca))
    base = f"https://{args.host}:{args.port}"
    headers = {"Authorization": "Bearer " + token}

    def get(path):
        with urllib.request.urlopen(
            urllib.request.Request(base + path, headers=headers),
            context=https,
            timeout=20,
        ) as response:
            return response.read()

    rows = json.loads(get("/api/boa/v1/audio-files?limit=100"))["items"]
    row = next(
        row
        for row in rows
        if row["source"] == "clip_direct"
        and row["sha256"] == digest.hex()
        and session in row["filename"]
    )
    assert (
        hashlib.sha256(
            get("/api/boa/v1/audio-files/" + row["id"] + "/content")
        ).digest()
        == digest
    )
    print(
        json.dumps(
            {
                "passed": True,
                "dtls_certificate_and_ip_verified": True,
                "https_certificate_and_ip_verified": True,
                "durable_bytes": len(body),
                "sha256": digest.hex(),
                "file_id": row["id"],
                "listed_and_downloaded": True,
            }
        )
    )


if __name__ == "__main__":
    main()
