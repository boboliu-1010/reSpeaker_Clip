"""Developer-only provisioning. Credentials go to private files, never logs."""

import argparse
import os
import secrets
import sqlite3
from pathlib import Path

from registry import Registry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    user = sub.add_parser("add-user")
    user.add_argument("user")
    device = sub.add_parser("add-device")
    device.add_argument("device")
    device.add_argument("--owner", required=True)
    for command in (user, device):
        command.add_argument(
            "--token-file",
            type=Path,
            help="read existing credential from a private file",
        )
        command.add_argument(
            "--token-out",
            type=Path,
            help="write a generated credential to a new private file",
        )
    revoke = sub.add_parser("revoke-device")
    revoke.add_argument("device")
    args = parser.parse_args()
    os.umask(0o077)
    registry = Registry(args.data_dir)
    if args.command == "revoke-device":
        registry.revoke_device(args.device)
        print("Device credential revoked; historical files retain their owner.")
        return
    if bool(args.token_file) == bool(args.token_out):
        parser.error("Choose exactly one of --token-file or --token-out")
    token = (
        args.token_file.read_text().strip()
        if args.token_file
        else secrets.token_urlsafe(32)
    )
    if args.token_out:
        args.token_out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Exclusive creation: never overwrite another credential.
        with args.token_out.open("x") as output:
            output.write(token + "\n")
        args.token_out.chmod(0o600)
    try:
        if args.command == "add-user":
            registry.add_user(args.user, token)
        else:
            registry.add_device(args.device, args.owner, token)
    except (ValueError, sqlite3.IntegrityError):
        parser.error(
            "Invalid or already registered identity/credential; no registration changed"
        )
    print("Registered. Credential stored in the specified private file.")


if __name__ == "__main__":
    main()
