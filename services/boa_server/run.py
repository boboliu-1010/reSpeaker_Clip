"""Start one Boa service with HTTPS/TCP and DTLS/UDP on the same port."""

import argparse
import fcntl
import os
import select
import socket
import threading
from pathlib import Path

import uvicorn
from boa_app import create_app


def dtls_listener(host, port, tls_root):
    from dtls_server_transport import make_context
    from receiver import BoaReceiver

    context = make_context(tls_root)

    def start(registry):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((host, port))
        sock.setblocking(False)
        receiver = BoaReceiver(sock, context, registry)
        stopped = threading.Event()

        def dispatch():
            while not stopped.is_set():
                if select.select([sock], [], [], 0.2)[0]:
                    packet, peer = sock.recvfrom(65535)
                    receiver.dispatch(packet, peer)

        thread = threading.Thread(target=dispatch, daemon=True)
        thread.start()

        def stop():
            stopped.set()
            thread.join(2)
            receiver.close()
            sock.close()

        return stop

    return start


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9528)
    parser.add_argument(
        "--tls-root",
        type=Path,
        help="contains private/server-chain.pem and private/server.key",
    )
    parser.add_argument(
        "--http-only",
        action="store_true",
        help="loopback-only HTTP development mode, no DTLS",
    )
    parser.add_argument("--https-certfile", type=Path)
    parser.add_argument("--https-keyfile", type=Path)
    args = parser.parse_args()
    if bool(args.https_certfile) != bool(args.https_keyfile):
        parser.error("HTTPS certificate and key must be supplied together")
    if args.https_certfile and not args.tls_root:
        parser.error("HTTPS overrides require --tls-root for DTLS")
    if not args.tls_root and not (
        args.http_only and args.host in ("127.0.0.1", "localhost")
    ):
        parser.error("Provide --tls-root, or use --http-only on loopback")
    if args.http_only and args.tls_root:
        parser.error("--http-only and --tls-root are mutually exclusive")
    if not 1 <= args.port <= 65535:
        parser.error("Invalid port")
    os.umask(0o077)
    args.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (args.data_dir / "server.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        listener = (
            dtls_listener(args.host, args.port, args.tls_root)
            if args.tls_root
            else None
        )
        uvicorn.run(
            create_app(args.data_dir, listener),
            host=args.host,
            port=args.port,
            access_log=False,
            ssl_certfile=str(
                args.https_certfile or args.tls_root / "private/server-chain.pem"
            )
            if args.tls_root
            else None,
            ssl_keyfile=str(args.https_keyfile or args.tls_root / "private/server.key")
            if args.tls_root
            else None,
        )


if __name__ == "__main__":
    main()
