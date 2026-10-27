"""Validate app-only signed images and a fixed-layout upgrade bundle."""
import hashlib
import json
from pathlib import Path
import struct

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from migrate import PATCH_SHA256

ROLES = ('maintenance', 'firmware', 'rollback', 'patch', 'public_key')
LAYOUT = 'clip-v0.1.2-lfs109-to107-extpatch-v1'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def verify_image(data, public_key):
    if len(data) < 32 or len(data) > 0xe4000:
        raise ValueError('App image size is outside the supported partition')
    magic, load, header, protected, size, flags = struct.unpack_from('<IIHHII', data)
    if magic != 0x96f3b83d or header < 32 or flags or load:
        raise ValueError('Only plain signed MCUboot application images are supported')
    end = header + size + protected
    if end + 4 > len(data):
        raise ValueError('Truncated MCUboot image')
    if protected:
        if struct.unpack_from('<HH', data, header + size) != (0x6908, protected):
            raise ValueError('Invalid protected TLV area')
    magic, length = struct.unpack_from('<HH', data, end)
    if magic != 0x6907 or length < 4 or end + length != len(data):
        raise ValueError('Invalid image TLV area or trailing bytes')
    fields, pos = {}, end + 4
    while pos < len(data):
        if pos + 4 > len(data):
            raise ValueError('Truncated image TLV header')
        kind, reserved, length = struct.unpack_from('<BBH', data, pos)
        pos += 4
        if reserved or pos + length > len(data) or kind in fields:
            raise ValueError('Invalid or duplicate image TLV')
        fields[kind] = data[pos:pos+length]
        pos += length
    payload = data[:end]
    image_hash = hashlib.sha256(payload).digest()
    if fields.get(0x10) != image_hash:
        raise ValueError('MCUboot image SHA-256 mismatch')
    key = serialization.load_pem_public_key(public_key)
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size != 2048:
        raise ValueError('This upgrader supports the pinned RSA-2048 bootloader only')
    key_hash = hashlib.sha256(key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.PKCS1)).digest()
    if fields.get(1) != key_hash or len(fields.get(0x20, b'')) != 256:
        raise ValueError('Image signing key does not match bundle public key')
    key.verify(fields[0x20], payload, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256())
    return image_hash.hex()


class Bundle:
    def __init__(self, root):
        self.root = Path(root).resolve()
        raw = (self.root/'manifest.json').read_bytes()
        self.fingerprint = digest(raw)
        self.manifest = json.loads(raw)
        if self.manifest.get('schema') != 1 or self.manifest.get('layout') != LAYOUT:
            raise ValueError('Unsupported upgrade bundle/layout')
        self.assets, self.images = {}, {}
        for role in ROLES:
            entry = self.manifest['files'][role]
            path = self.root/entry['file']
            if path.resolve().parent != self.root or path.is_symlink():
                raise ValueError('Bundle assets must be regular files in bundle root')
            data = path.read_bytes()
            if digest(data) != entry['sha256']:
                raise ValueError(f'Bundle integrity mismatch: {role}')
            self.assets[role] = data
        if len(self.assets['patch']) != 87046 or digest(self.assets['patch']) != PATCH_SHA256:
            raise ValueError('Wi-Fi patch does not match the pinned SDK')
        for role in ('maintenance', 'firmware', 'rollback'):
            self.images[role] = verify_image(self.assets[role], self.assets['public_key'])
        if len(set(self.images.values())) != 3:
            raise ValueError('Maintenance, target and original-layout rollback images must differ')
