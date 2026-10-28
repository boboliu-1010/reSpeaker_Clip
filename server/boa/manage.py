"""Developer-only provisioning. Credentials go to private files, never logs."""

import argparse
import os
import secrets
import sqlite3
from pathlib import Path

from server.boa.registry import Registry


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
    role = sub.add_parser("set-role")
    role.add_argument("user")
    role.add_argument("role", choices=["user", "developer"])
    configuration = sub.add_parser('configure-device', help='Enable automatic Web configuration for an existing binding')
    configuration.add_argument('device')
    configuration.add_argument('--name', required=True, help='Exact name returned by AT+DEVICE')
    configuration.add_argument('--endpoint', required=True, help='Controlled DTLS host:port')
    configuration.add_argument('--token-file', type=Path, required=True)
    configuration.add_argument('--uid', help='Full lowercase hardware UID (never inferred from name)')
    cleanup = sub.add_parser('complete-device-cleanup', help='Developer-only acknowledgment of completed hardware handoff cleanup')
    cleanup.add_argument('device')
    cleanup.add_argument('--uid', required=True)
    cleanup.add_argument('--binding-id', required=True)
    cleanup.add_argument('--confirm-old-data-wifi-and-pairing-cleaned', action='store_true', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    registry = Registry(args.data_dir)
    if args.command == 'complete-device-cleanup':
        try:
            registry.complete_device_cleanup(args.device, args.uid, args.binding_id)
        except ValueError:
            parser.error('Cleanup must match the revoked device UID and binding')
        print('Developer cleanup acknowledgment recorded. No hardware action was performed.')
        return
    if args.command == 'configure-device':
        from server.boa.device_configurations import DeviceConfigurations, ConfigurationUnavailable
        try:
            token = args.token_file.read_text().strip()
            DeviceConfigurations(registry).register(args.device, args.name, args.endpoint, token, uid=args.uid)
        except (OSError, ValueError, ConfigurationUnavailable):
            parser.error('Cannot register device configuration; check private files and active binding')
        print('Automatic device configuration registered. Existing credential and binding preserved.')
        return
    if args.command == "set-role":
        try:
            registry.set_role(args.user, args.role)
        except ValueError:
            parser.error("Unknown user")
        print("Role updated.")
        return
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
