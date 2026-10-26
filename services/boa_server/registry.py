"""Private user/device registry and recoverable DTLS file index."""

import hashlib
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,32}\Z")
TOKEN = re.compile(r"[A-Za-z0-9_-]{32,96}\Z")


def token_hash(token):
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        raise ValueError("Invalid credential format")
    return hashlib.sha256(token.encode("ascii")).hexdigest()


class Registry:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._stores = {}
        self._lock = threading.RLock()
        with self.db() as db:
            db.executescript("""PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,token_hash TEXT UNIQUE NOT NULL,active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS bindings(id TEXT PRIMARY KEY,device TEXT NOT NULL,owner TEXT NOT NULL,token_hash TEXT UNIQUE NOT NULL,epoch INTEGER NOT NULL,active INTEGER NOT NULL,UNIQUE(device,epoch));
                CREATE UNIQUE INDEX IF NOT EXISTS active_device ON bindings(device) WHERE active=1;
                CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,owner TEXT NOT NULL,binding TEXT NOT NULL,device TEXT NOT NULL,session TEXT NOT NULL,segment INTEGER NOT NULL,size INTEGER NOT NULL,sha256 TEXT NOT NULL,object_id TEXT NOT NULL,created INTEGER NOT NULL,state TEXT NOT NULL,UNIQUE(binding,session,segment));""")
        (self.root / "registry.sqlite3").chmod(0o600)

    @contextmanager
    def db(self):
        connection = sqlite3.connect(self.root / "registry.sqlite3", timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def add_user(self, user, token):
        if not IDENTIFIER.fullmatch(user):
            raise ValueError("Invalid user ID")
        with self.db() as db:
            db.execute(
                "INSERT INTO users(id,token_hash) VALUES (?,?)",
                (user, token_hash(token)),
            )

    def user_for_token(self, token):
        try:
            digest = token_hash(token)
        except ValueError:
            return None
        with self.db() as db:
            row = db.execute(
                "SELECT id FROM users WHERE token_hash=? AND active=1", (digest,)
            ).fetchone()
        return row["id"] if row else None

    def users(self):
        with self.db() as db:
            return [
                row["id"] for row in db.execute("SELECT id FROM users WHERE active=1")
            ]

    def add_device(self, device, owner, token):
        if not IDENTIFIER.fullmatch(device):
            raise ValueError("Invalid device ID")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT 1 FROM users WHERE id=? AND active=1", (owner,)
            ).fetchone():
                raise ValueError("Unknown user")
            epoch = db.execute(
                "SELECT COALESCE(MAX(epoch),0)+1 FROM bindings WHERE device=?",
                (device,),
            ).fetchone()[0]
            db.execute(
                "INSERT INTO bindings VALUES (?,?,?,?,?,1)",
                (uuid.uuid4().hex, device, owner, token_hash(token), epoch),
            )

    def revoke_device(self, device):
        with self.db() as db:
            db.execute("UPDATE bindings SET active=0 WHERE device=?", (device,))

    def device_for_token(self, device, token):
        try:
            digest = token_hash(token)
        except ValueError:
            return None
        with self.db() as db:
            row = db.execute(
                "SELECT * FROM bindings WHERE device=? AND token_hash=? AND active=1",
                (device, digest),
            ).fetchone()
        return dict(row) if row else None

    def store_for(self, binding):
        from resume_store import ResumeStore

        with self._lock:
            if binding not in self._stores:
                directory = self.root / "clip" / binding
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                self._stores[binding] = ResumeStore(directory, threading.Lock())
            return self._stores[binding]

    def receive(self, binding, identity):
        from resume_store import ResumeError

        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM sources WHERE binding=? AND session=? AND segment=?",
                (binding["id"], identity["session"], identity["segment"]),
            ).fetchone()
            if row:
                if (
                    row["size"] != identity["size"]
                    or row["sha256"] != identity["sha256"]
                ):
                    raise ResumeError(409, "identity_conflict")
                return row["id"]
            fid = uuid.uuid4().hex
            db.execute(
                "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    fid,
                    binding["owner"],
                    binding["id"],
                    identity["device"],
                    identity["session"],
                    identity["segment"],
                    identity["size"],
                    identity["sha256"],
                    identity["object_id"],
                    int(time.time()),
                    "receiving",
                ),
            )
            return fid

    def reconcile(self, owner=None):
        with self.db() as db:
            rows = db.execute(
                "SELECT * FROM sources WHERE state='receiving' AND (? IS NULL OR owner=?)",
                (owner, owner),
            ).fetchall()
        for row in rows:
            path = self.raw_path(row)
            try:
                if path.stat().st_size != row["size"]:
                    continue
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for block in iter(lambda: stream.read(65536), b""):
                        digest.update(block)
                if digest.hexdigest() != row["sha256"]:
                    continue
            except FileNotFoundError:
                continue
            with self.db() as db:
                db.execute("UPDATE sources SET state='ready' WHERE id=?", (row["id"],))

    def raw_path(self, row):
        return self.root / "clip" / row["binding"] / (row["object_id"] + ".bin")

    def clip_files(self, owner):
        self.reconcile(owner)
        with self.db() as db:
            rows = db.execute(
                "SELECT * FROM sources WHERE owner=? AND state='ready'", (owner,)
            ).fetchall()
        return [self.public(row) for row in rows]

    def raw_file(self, owner, fid):
        with self.db() as db:
            row = db.execute(
                "SELECT * FROM sources WHERE id=? AND owner=? AND state='ready'",
                (fid, owner),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def public(row):
        return {
            "id": row["id"],
            "filename": f"Clip-{row['session']}-{row['segment']}.bin",
            "size": row["size"],
            "sha256": row["sha256"],
            "created": row["created"],
            "source": "clip_direct",
            "mime": "application/octet-stream",
            "state": "complete",
        }
