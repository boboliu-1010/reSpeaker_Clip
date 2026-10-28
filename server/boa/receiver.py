"""DTLS v3 extension; original framing, checksums and receiver stay unchanged."""

import logging
import sqlite3

from server.dtls_upload_protocol import OPEN, parse_open, unpack
from server.dtls_upload_server import Receiver
from server.dtls_upload_session import UploadSession
from server.resume_store import ResumeError

log = logging.getLogger(__name__)


class OwnedSession(UploadSession):
    def __init__(self, registry, claim_owner=None):
        super().__init__(None, {}, claim_owner)
        self.registry = registry
        self.binding = None

    def feed(self, packet, now=None):
        kind, _, _, body = unpack(packet)
        if kind == OPEN:
            identity, supplied = parse_open(body)
            binding = self.registry.device_for_token(identity["device"], supplied)
            if not binding:
                raise ResumeError(403, "unauthorized_device")
            if self.binding and self.binding["id"] != binding["id"]:
                raise ResumeError(409, "connection_binding_conflict")
            try:
                self.registry.receive(binding, identity)
            except (OSError, sqlite3.Error) as exc:
                raise ResumeError(507, "index_unavailable") from exc
            self.binding = binding
            self.store = self.registry.store_for(binding["id"])
            self.identities = {identity["device"]: supplied}
        # Revalidate enrollment for every frame: revoked connections cannot keep writing.
        elif self.binding and not self.registry.device_for_token(
            self.binding["device"], self.identities[self.binding["device"]]
        ):
            raise ResumeError(403, "revoked_device")
        responses = super().feed(packet, now)
        if self.writer and self.writer.stored:
            try:
                self.registry.reconcile(self.binding["owner"])
            except (OSError, sqlite3.Error):
                # Receiving identity is already durable; the service reconciler retries.
                log.error("Clip file index update pending")
        return responses


class BoaReceiver(Receiver):
    def __init__(self, sock, context, registry):
        super().__init__(sock, context, None, {})
        self.registry = registry

    def serve(self, client):
        client.session = OwnedSession(
            self.registry, lambda device: self.claim(client, device)
        )
        return super().serve(client)
