"""Private, developer-managed device configuration delivery. No token rotation."""

import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool

UID = re.compile(r'(?:[0-9a-f]{2}){8,32}\Z')
UINT32_MAX = 4294967295

TARGET = re.compile(r'[A-Za-z0-9.-]{1,95}:([0-9]{1,5})\Z')


class ConfigurationUnavailable(Exception):
    pass


def valid_name(name):
    return (isinstance(name, str) and 1 <= len(name.encode('utf-8')) <= 64
            and not any(ord(char) < 32 or ord(char) == 127 for char in name))


class DeviceConfigurations:
    def __init__(self, registry):
        self.registry = registry
        self.path = registry.root / 'device-configurations.json'

    def _read(self, missing_ok=False):
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_mode & 0o077 or info.st_size > 1024 * 1024):
                    raise ConfigurationUnavailable()
                rows = json.loads(stream.read(1024 * 1024 + 1))
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ConfigurationUnavailable()
            devices, aliases, uids, bindings, credentials = set(), {}, set(), set(), set()
            for row in rows:
                try:
                    self._validate(row['device_name'], row['endpoint'], row['device_id'], row['device_token'])
                    from server.boa.registry import IDENTIFIER
                    if not IDENTIFIER.fullmatch(row['owner']) or not re.fullmatch('[0-9a-f]{32}', row['binding_id']):
                        raise ValueError()
                    device, alias, uid = row['device_id'], (row['owner'], row['device_name']), row.get('device_uid')
                    if (device in devices or row['binding_id'] in bindings or row['device_token'] in credentials
                            or (alias in aliases and (not uid or not aliases[alias]))
                            or (uid is not None and (not UID.fullmatch(uid) or uid in uids))):
                        raise ValueError()
                    devices.add(device)
                    bindings.add(row['binding_id'])
                    credentials.add(row['device_token'])
                    aliases[alias] = uid
                    if uid is not None:
                        uids.add(uid)
                        if type(row.get('revision')) is not int or not 1 <= row['revision'] <= UINT32_MAX:
                            raise ValueError()
                except (KeyError, TypeError, ValueError):
                    raise ConfigurationUnavailable() from None
            return rows
        except FileNotFoundError:
            if missing_ok:
                return []
            raise ConfigurationUnavailable() from None
        except (OSError, ValueError, TypeError):
            raise ConfigurationUnavailable() from None

    @staticmethod
    def _validate(name, endpoint, device, token):
        match = TARGET.fullmatch(endpoint) if isinstance(endpoint, str) else None
        from server.boa.registry import IDENTIFIER, token_hash
        if (not valid_name(name) or not match or not 1 <= int(match[1]) <= 65535
                or not isinstance(device, str) or not IDENTIFIER.fullmatch(device)):
            raise ValueError('Invalid device configuration')
        token_hash(token)
        if len(f'AT+UPLOADCFG={endpoint.replace(":", ",")},{device},{token}'.encode()) > 255:
            raise ValueError('Device configuration exceeds BLE command limit')

    def lookup(self, owner, name):
        rows = self._read()
        matches = [row for row in rows if row.get('owner') == owner and row.get('device_name') == name]
        if not matches:
            return None
        if len(matches) != 1:
            raise ConfigurationUnavailable()
        row = matches[0]
        try:
            self._validate(name, row['endpoint'], row['device_id'], row['device_token'])
            binding = self.registry.device_for_token(row['device_id'], row['device_token'])
            if not binding or binding['owner'] != owner or binding['id'] != row['binding_id']:
                return None
            return {key: row[key] for key in ('device_id', 'device_name', 'owner', 'endpoint', 'device_token')}
        except (KeyError, ValueError, TypeError):
            raise ConfigurationUnavailable() from None

    @contextmanager
    def _registration_lock(self):
        lock = self.registry.root / 'device-configurations.lock'
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    @staticmethod
    def fingerprint(row):
        # Includes credentials only inside a one-way digest; never returned or logged.
        fields = ('device_id', 'device_uid', 'device_name', 'owner', 'binding_id', 'endpoint', 'device_token')
        return hashlib.sha256(json.dumps({key: row.get(key) for key in fields},
                                        sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    def _write(self, rows):
        fd, temporary = tempfile.mkstemp(prefix='.device-configurations-', dir=self.registry.root)
        try:
            with os.fdopen(fd, 'w') as output:
                json.dump(rows, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.registry.root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def register(self, device, name, endpoint, token, uid=None):
        self._validate(name, endpoint, device, token)
        if uid is not None and (not isinstance(uid, str) or not UID.fullmatch(uid)):
            raise ValueError('Invalid full device UID')
        with self._registration_lock(), self.registry.db() as db:
            db.execute('BEGIN IMMEDIATE')
            from server.boa.registry import token_hash
            binding = db.execute('SELECT * FROM bindings WHERE device=? AND token_hash=? AND active=1',
                                 (device, token_hash(token))).fetchone()
            if not binding:
                raise ValueError('Credential does not match an active registered device')
            rows = self._read(missing_ok=True)
            existing = next((row for row in rows if row['device_id'] == device), None)
            pin = db.execute('SELECT uid FROM device_uids WHERE device=?', (device,)).fetchone()
            # Legacy CLI updates preserve an enrolled UID, never infer one from a name.
            uid = uid if uid is not None else (pin['uid'] if pin else None)
            if pin and pin['uid'] != uid:
                raise ValueError('Device UID cannot be reassigned')
            if uid:
                other = db.execute('SELECT device FROM device_uids WHERE uid=?', (uid,)).fetchone()
                if other and other['device'] != device:
                    raise ValueError('UID already pinned to another device')
            rows = [row for row in rows if row['device_id'] != device]
            if any(row['owner'] == binding['owner'] and row['device_name'] == name
                   and (not uid or not row.get('device_uid')) for row in rows):
                raise ValueError('Device name is ambiguous for this user')
            row = dict(device_id=device, device_name=name, endpoint=endpoint,
                       device_token=token, owner=binding['owner'], binding_id=binding['id'])
            if uid:
                if not 1 <= binding['epoch'] <= UINT32_MAX:
                    raise ValueError('Invalid binding epoch')
                row['device_uid'] = uid
                previous = db.execute('SELECT * FROM binding_profiles WHERE binding=?', (binding['id'],)).fetchone()
                digest = self.fingerprint(row)
                revision = (previous['revision'] + (previous['config_hash'] != digest)) if previous else 1
                if revision > UINT32_MAX:
                    raise ValueError('Configuration revision exhausted')
                row['revision'] = revision
                command = f"AT+BINDCFG={endpoint.replace(':', ',')},{device},{token},{binding['id']},{binding['epoch']},{revision}"
                if len(command.encode()) > 255:
                    raise ValueError('Device binding exceeds BLE command limit')
                db.execute('INSERT OR IGNORE INTO device_uids VALUES (?,?)', (uid, device))
                db.execute('INSERT INTO binding_profiles(binding,uid,revision,config_hash) VALUES (?,?,?,?) '
                           'ON CONFLICT(binding) DO UPDATE SET revision=excluded.revision,config_hash=excluded.config_hash',
                           (binding['id'], uid, revision, digest))
            rows.append(row)
            if row != existing:
                self._write(rows)

    def owned_binding(self, db, owner, device):
        # Only the latest assignment is manageable; old files retain their original owner.
        row = db.execute('SELECT * FROM bindings WHERE device=? ORDER BY epoch DESC LIMIT 1', (device,)).fetchone()
        if not row or row['owner'] != owner:
            raise HTTPException(404, 'device_not_found')
        return row

    def current_profile(self, db, binding):
        rows = self._read()
        row = next((row for row in rows if row['device_id'] == binding['device']), None)
        if not row or row['binding_id'] != binding['id'] or row['owner'] != binding['owner']:
            raise HTTPException(409, 'binding_configuration_unavailable')
        profile = db.execute('SELECT * FROM binding_profiles WHERE binding=?', (binding['id'],)).fetchone()
        if not row.get('device_uid') or not profile:
            raise HTTPException(409, 'device_uid_not_enrolled')
        from server.boa.registry import token_hash
        pin = db.execute('SELECT uid FROM device_uids WHERE device=?', (binding['device'],)).fetchone()
        if (not pin or pin['uid'] != row['device_uid'] or profile['uid'] != row['device_uid']
                or row['revision'] != profile['revision'] or self.fingerprint(row) != profile['config_hash']
                or token_hash(row['device_token']) != binding['token_hash']):
            raise ConfigurationUnavailable()
        if not 1 <= binding['epoch'] <= UINT32_MAX:
            raise ConfigurationUnavailable()
        return row, profile

    def prepare(self, owner, device, uid):
        with self.registry.db() as db:
            db.execute('BEGIN IMMEDIATE')
            binding = self.owned_binding(db, owner, device)
            if not binding['active']:
                raise HTTPException(409, 'binding_revoked')
            row, profile = self.current_profile(db, binding)
            if row['device_uid'] != uid:
                raise HTTPException(409, 'device_uid_mismatch')
            return dict(device_id=device, device_uid=uid, device_name=row['device_name'],
                        binding_id=binding['id'], owner_id=owner, epoch=binding['epoch'],
                        revision=profile['revision'], endpoint=row['endpoint'], device_token=row['device_token'],
                        state='provisioned' if profile['confirmed_revision'] == profile['revision'] else 'assigned')

    def confirm(self, owner, device, body):
        with self.registry.db() as db:
            db.execute('BEGIN IMMEDIATE')
            binding = self.owned_binding(db, owner, device)
            if not binding['active']:
                raise HTTPException(409, 'binding_revoked')
            row, profile = self.current_profile(db, binding)
            if (row['device_uid'] != body.device_uid or binding['id'] != body.binding_id
                    or profile['revision'] != body.revision):
                raise HTTPException(409, 'binding_configuration_changed')
            db.execute('UPDATE binding_profiles SET confirmed_revision=? WHERE binding=?',
                       (body.revision, body.binding_id))
        return dict(state='provisioned', binding_id=body.binding_id, revision=body.revision)

    def devices(self, owner):
        self.registry.reconcile(owner)
        with self.registry.db() as db:
            # Validate source globally: duplicate/corrupt credentials fail closed.
            rows = self._read(missing_ok=True)
            items = []
            bindings = db.execute('SELECT * FROM bindings b WHERE owner=? AND epoch='
                                  '(SELECT MAX(epoch) FROM bindings WHERE device=b.device)', (owner,)).fetchall()
            for binding in bindings:
                profile = db.execute('SELECT * FROM binding_profiles WHERE binding=?', (binding['id'],)).fetchone()
                row = next((row for row in rows if row['binding_id'] == binding['id']), None)
                if binding['active'] and profile:
                    row, profile = self.current_profile(db, binding)
                cleanup = db.execute('SELECT pending FROM device_cleanup_locks WHERE binding=?', (binding['id'],)).fetchone()
                pin = db.execute('SELECT uid FROM device_uids WHERE device=?', (binding['device'],)).fetchone()
                receipt = db.execute("SELECT MAX(created) FROM sources WHERE binding=? AND state='ready'",
                                     (binding['id'],)).fetchone()[0]
                items.append(dict(device_id=binding['device'], device_uid=profile['uid'] if profile else pin['uid'] if pin else None,
                    device_name=row['device_name'] if row else binding['device'], binding_id=binding['id'],
                    epoch=binding['epoch'], revision=profile['revision'] if profile else None,
                    provisioning_state=('revoked' if not binding['active'] else
                        'provisioned' if profile and profile['confirmed_revision'] == profile['revision'] else 'assigned'),
                    last_received_at=receipt, last_upload_revision=None,
                    device_cleanup_pending=bool(cleanup and cleanup['pending'])))
        return dict(items=items)

    def revoke(self, owner, device):
        with self.registry.db() as db:
            db.execute('BEGIN IMMEDIATE')
            binding = self.owned_binding(db, owner, device)
            pending = self.registry.revoke_binding(db, binding['id'])
        return dict(state='revoked', device_cleanup_pending=pending)


class DeviceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    device_name: str = Field(min_length=1, max_length=64)


def install_device_configurations(app, registry, sessions):
    profiles = DeviceConfigurations(registry)
    install_binding_routes(app, profiles, sessions)

    @app.post('/api/boa/v1/devices/configuration')
    def configuration(body: DeviceRequest, request: Request):
        owner, _ = sessions.principal(request)
        if owner is None:
            raise HTTPException(401, 'Unauthorized')
        if not valid_name(body.device_name):
            raise HTTPException(422, 'Invalid device name')
        try:
            result = profiles.lookup(owner, body.device_name)
        except ConfigurationUnavailable:
            raise HTTPException(503, '设备自动配置暂不可用，请联系开发者') from None
        if result is None:
            raise HTTPException(404, '此设备尚未登记到当前用户，请联系开发者')
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})


class BindingRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    device_uid: str = Field(pattern=r'^(?:[0-9a-f]{2}){8,32}$')


class BindingConfirmation(BindingRequest):
    binding_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    revision: int = Field(strict=True, ge=1, le=UINT32_MAX)
    saved: StrictBool


def install_binding_routes(app, profiles, sessions):
    def owner_for(request):
        owner, _ = sessions.principal(request)
        if owner is None:
            raise HTTPException(401, 'Unauthorized')
        return owner

    def result(call):
        try:
            return JSONResponse(call(), headers={'Cache-Control': 'no-store'})
        except ConfigurationUnavailable:
            raise HTTPException(503, 'device_configuration_source_unavailable') from None

    @app.get('/api/boa/v1/devices')
    def devices(request: Request):
        owner = owner_for(request)
        return result(lambda: profiles.devices(owner))

    @app.post('/api/boa/v1/devices/{device}/binding')
    def binding(device: str, body: BindingRequest, request: Request):
        owner = owner_for(request)
        return result(lambda: profiles.prepare(owner, device, body.device_uid))

    @app.post('/api/boa/v1/devices/{device}/binding/confirm')
    def confirm(device: str, body: BindingConfirmation, request: Request):
        owner = owner_for(request)
        if body.saved is not True:
            raise HTTPException(422, 'saved_confirmation_required')
        return result(lambda: profiles.confirm(owner, device, body))

    @app.delete('/api/boa/v1/devices/{device}/binding')
    def revoke(device: str, request: Request):
        owner = owner_for(request)
        return result(lambda: profiles.revoke(owner, device))
