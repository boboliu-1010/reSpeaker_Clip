"""One Boa service: Web on 9529, API/DTLS on 9528, one shared data directory."""

import argparse
import asyncio
import fcntl
import os
import select
import signal
import socket
import threading
from contextlib import contextmanager
from pathlib import Path

import uvicorn
from server.boa.boa_app import create_app
from server.boa.frontend import Frontend


class ManagedServer(uvicorn.Server):
    @contextmanager
    def capture_signals(self):
        # Both listeners are stopped by one process-level signal handler.
        yield


async def serve_listeners(backend, host, port, web_port, certificate=None, key=None):
    common = {'host': host, 'access_log': False, 'ssl_certfile': certificate,
              'ssl_keyfile': key, 'timeout_graceful_shutdown': 15}
    servers = [ManagedServer(uvicorn.Config(backend, port=port, lifespan='on', **common))]
    if web_port:
        servers.append(ManagedServer(uvicorn.Config(Frontend(backend), port=web_port,
                                                     lifespan='off', **common)))

    def stop_all(signum, _frame):
        for server in servers:
            if server.should_exit and signum == signal.SIGINT:
                server.force_exit = True
            server.should_exit = True

    previous = {}
    if threading.current_thread() is threading.main_thread():
        previous = {sig: signal.signal(sig, stop_all) for sig in (signal.SIGINT, signal.SIGTERM)}

    async def serve_one(server):
        try:
            await server.serve()
        except SystemExit as error:
            raise RuntimeError('Boa listener failed to start') from error

    tasks = [asyncio.create_task(serve_one(server)) for server in servers]
    try:
        finished, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in finished:
            task.result()
    finally:
        for server in servers:
            server.should_exit = True
        await asyncio.gather(*tasks, return_exceptions=True)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def dtls_listener(host, port, tls_root):
    from server.boa.receiver import BoaReceiver

    from server.dtls_server_transport import make_context

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
    parser.add_argument("--web-port", type=int, default=9529,
                        help="Web HTTPS port; 0 disables the separate Web listener")
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
    parser.add_argument("--allow-id-login", action="store_true", default=os.environ.get('BOA_ALLOW_ID_LOGIN') == '1',
                        help="Enable passwordless ID selection on a trusted development network")
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
    if not 0 <= args.web_port <= 65535:
        parser.error("Invalid Web port")
    if args.web_port == args.port:
        parser.error("Web and API ports must be different")
    os.umask(0o077)
    args.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (args.data_dir / "server.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        listener = (
            dtls_listener(args.host, args.port, args.tls_root)
            if args.tls_root
            else None
        )
        asyncio.run(serve_listeners(
            create_app(args.data_dir, listener, allow_id_login=args.allow_id_login),
            args.host, args.port, args.web_port,
            certificate=str(
                args.https_certfile or args.tls_root / "private/server-chain.pem"
            )
            if args.tls_root
            else None,
            key=str(args.https_keyfile or args.tls_root / "private/server.key")
            if args.tls_root
            else None,
        ))


if __name__ == "__main__":
    main()
