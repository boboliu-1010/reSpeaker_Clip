import argparse
import fcntl
import os
import secrets
from pathlib import Path

import uvicorn

from app import create_app


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--data-dir",
        type=Path,
        default=Path.home() / "Library/Application Support/BoaAudioStorage",
    )
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--ssl-certfile", type=Path)
    p.add_argument("--ssl-keyfile", type=Path)
    a = p.parse_args()
    if bool(a.ssl_certfile) != bool(a.ssl_keyfile):
        p.error("--ssl-certfile and --ssl-keyfile must be provided together")
    os.umask(0o077)
    a.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (a.data_dir / "server.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        token = a.data_dir / "token"
        if not token.exists():
            token.write_text(secrets.token_urlsafe(32))
        token.chmod(0o600)
        uvicorn.run(
            create_app(a.data_dir, token.read_text().strip()),
            host=a.host,
            port=a.port,
            access_log=False,
            # Keep the server window above Dart HttpClient's 15s idle pool.
            # A short server timeout can race with large-file verification.
            timeout_keep_alive=30,
            ssl_certfile=str(a.ssl_certfile) if a.ssl_certfile else None,
            ssl_keyfile=str(a.ssl_keyfile) if a.ssl_keyfile else None,
        )


if __name__ == "__main__":
    main()
