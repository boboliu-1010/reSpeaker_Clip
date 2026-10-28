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
                CREATE TABLE IF NOT EXISTS user_roles(user TEXT PRIMARY KEY,role TEXT NOT NULL CHECK(role IN ('user','developer')));
                CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,token_hash TEXT UNIQUE NOT NULL,active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS bindings(id TEXT PRIMARY KEY,device TEXT NOT NULL,owner TEXT NOT NULL,token_hash TEXT UNIQUE NOT NULL,epoch INTEGER NOT NULL,active INTEGER NOT NULL,UNIQUE(device,epoch));
                CREATE UNIQUE INDEX IF NOT EXISTS active_device ON bindings(device) WHERE active=1;
                CREATE TABLE IF NOT EXISTS device_uids(uid TEXT PRIMARY KEY,device TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS binding_profiles(binding TEXT PRIMARY KEY,uid TEXT NOT NULL,revision INTEGER NOT NULL,config_hash TEXT NOT NULL,confirmed_revision INTEGER,cleanup_pending INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS device_cleanup_locks(binding TEXT PRIMARY KEY,uid TEXT,pending INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS device_cleanup_history(binding TEXT PRIMARY KEY,uid TEXT NOT NULL,completed INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,owner TEXT NOT NULL,binding TEXT NOT NULL,device TEXT NOT NULL,session TEXT NOT NULL,segment INTEGER NOT NULL,size INTEGER NOT NULL,sha256 TEXT NOT NULL,object_id TEXT NOT NULL,created INTEGER NOT NULL,state TEXT NOT NULL,UNIQUE(binding,session,segment));""")
            # Old revoked assignments have no hardware cleanup proof. Retain ownership
            # history and lock them until a developer explicitly acknowledges cleanup.
            db.execute("INSERT OR IGNORE INTO device_cleanup_locks(binding,uid,pending) "
                       "SELECT b.id,u.uid,CASE WHEN h.binding IS NULL THEN 1 ELSE 0 END "
                       "FROM bindings b LEFT JOIN device_uids u ON u.device=b.device "
                       "LEFT JOIN device_cleanup_history h ON h.binding=b.id WHERE b.active=0")
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

    def role(self, user):
        with self.db() as db:
            row = db.execute("SELECT role FROM user_roles WHERE user=?", (user,)).fetchone()
        return row["role"] if row else "user"

    def set_role(self, user, role):
        if role not in ("user", "developer"):
            raise ValueError("Invalid role")
        with self.db() as db:
            if not db.execute("SELECT 1 FROM users WHERE id=? AND active=1", (user,)).fetchone():
                raise ValueError("Unknown user")
            db.execute("INSERT INTO user_roles VALUES (?,?) ON CONFLICT(user) DO UPDATE SET role=excluded.role", (user, role))

    def add_device(self, device, owner, token):
        if not IDENTIFIER.fullmatch(device):
            raise ValueError("Invalid device ID")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT 1 FROM users WHERE id=? AND active=1", (owner,)
            ).fetchone():
                raise ValueError("Unknown user")
            if db.execute(
                "SELECT 1 FROM bindings b LEFT JOIN device_cleanup_history h ON h.binding=b.id "
                "LEFT JOIN device_cleanup_locks l ON l.binding=b.id "
                "WHERE b.device=? AND b.active=0 AND (h.binding IS NULL OR l.pending=1)", (device,)
            ).fetchone():
                raise ValueError("Device handoff requires developer-confirmed cleanup")
            epoch = db.execute(
                "SELECT COALESCE(MAX(epoch),0)+1 FROM bindings WHERE device=?",
                (device,),
            ).fetchone()[0]
            db.execute(
                "INSERT INTO bindings VALUES (?,?,?,?,?,1)",
                (uuid.uuid4().hex, device, owner, token_hash(token), epoch),
            )

    def revoke_binding(self, db, binding_id):
        """Revoke and durably lock even pre-UID assignments in the same transaction."""
        binding = db.execute("SELECT * FROM bindings WHERE id=?", (binding_id,)).fetchone()
        if not binding:
            raise ValueError("Unknown binding")
        pin = db.execute("SELECT uid FROM device_uids WHERE device=?", (binding['device'],)).fetchone()
        completed = db.execute("SELECT 1 FROM device_cleanup_history WHERE binding=?", (binding_id,)).fetchone()
        db.execute("INSERT OR IGNORE INTO device_cleanup_locks VALUES (?,?,?)",
                   (binding_id, pin['uid'] if pin else None, 0 if completed else 1))
        db.execute("UPDATE bindings SET active=0 WHERE id=?", (binding_id,))
        pending = db.execute("SELECT pending FROM device_cleanup_locks WHERE binding=?", (binding_id,)).fetchone()[0]
        db.execute("UPDATE binding_profiles SET cleanup_pending=? WHERE binding=?", (pending, binding_id))
        return bool(pending)

    def revoke_device(self, device):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            # Also covers historical legacy assignments without a profile or UID.
            for row in db.execute("SELECT id FROM bindings WHERE device=?", (device,)).fetchall():
                self.revoke_binding(db, row['id'])

    def complete_device_cleanup(self, device, uid, binding_id):
        """Developer acknowledgment after old data, Wi-Fi and pairing cleanup.

        A legacy device must first have its full hardware UID read explicitly.
        This records that UID, never derives it from a BLE name, never clears
        hardware remotely and never creates a new ownership.
        """
        if not isinstance(uid, str) or not re.fullmatch(r'(?:[0-9a-f]{2}){8,32}', uid):
            raise ValueError("Cleanup requires full lowercase hardware UID")
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT active FROM bindings WHERE device=? AND id=?",
                             (device, binding_id)).fetchone()
            if not row or row['active']:
                raise ValueError("Cleanup acknowledgment does not match revoked binding")
            pin = db.execute("SELECT uid,device FROM device_uids WHERE uid=? OR device=?", (uid, device)).fetchall()
            if any(item['uid'] != uid or item['device'] != device for item in pin):
                raise ValueError("Cleanup UID does not match pinned device")
            profile = db.execute("SELECT uid FROM binding_profiles WHERE binding=?", (binding_id,)).fetchone()
            if profile and profile['uid'] != uid:
                raise ValueError("Cleanup UID does not match binding")
            lock = db.execute("SELECT uid FROM device_cleanup_locks WHERE binding=?", (binding_id,)).fetchone()
            if lock and lock['uid'] is not None and lock['uid'] != uid:
                raise ValueError("Cleanup UID does not match revoked assignment")
            db.execute("INSERT OR IGNORE INTO device_uids VALUES (?,?)", (uid, device))
            db.execute("INSERT INTO device_cleanup_locks VALUES (?,?,0) ON CONFLICT(binding) "
                       "DO UPDATE SET uid=excluded.uid,pending=0", (binding_id, uid))
            db.execute("UPDATE binding_profiles SET cleanup_pending=0 WHERE binding=?", (binding_id,))
            db.execute("INSERT OR IGNORE INTO device_cleanup_history VALUES (?,?,?)",
                       (binding_id, uid, int(time.time())))

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
        from server.resume_store import ResumeStore

        with self._lock:
            if binding not in self._stores:
                directory = self.root / "clip" / binding
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                self._stores[binding] = ResumeStore(directory, threading.Lock())
            return self._stores[binding]

    def receive(self, binding, identity):
        from server.resume_store import ResumeError

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
