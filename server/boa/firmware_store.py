"""Small, isolated firmware library for the local Web prototype."""

import hashlib
import json
import re
import sqlite3
import struct
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa, utils
from fastapi import HTTPException

MAX_SIZE = 8 * 1024 * 1024
# 0xea000-byte application slot, with a conservative internal erase-page
# reserve for MCUboot metadata. Re-check the built partition map before flashing.
BOA_CLIP_OTA_MAX_SIZE = 0xEA000 - 4096
PROFILES = {
    "ble-standard": "标准 BLE SMP 应用核，需确认板型与网络核兼容",
    "dtls-upload": "历史 DTLS 配置：禁用应用 DFU",
    "boa-dtls-ota-v1": "DTLS + 原生 BLE OTA，RSA-2048 应用核，overwrite-only",
    "demo-offline": "演示制品，仅验证管理流程，禁止刷写",
}


def inspect_image(data, key_path):
    if len(data) < 32 or struct.unpack_from("<I", data)[0] != 0x96F3B83D:
        raise HTTPException(422, "需要 MCUboot 应用核 signed.bin，不能使用 HEX/ZIP")
    header_size, protected_size, image_size, flags = struct.unpack_from("<HHII", data, 8)
    end = header_size + image_size + protected_size
    if header_size < 32 or image_size == 0 or end + 4 > len(data) or flags != 0:
        raise HTTPException(422, "不支持的镜像布局或标志")
    if protected_size:
        offset = header_size + image_size
        magic, size = struct.unpack_from("<HH", data, offset)
        if magic != 0x6908 or size != protected_size:
            raise HTTPException(422, "受保护 TLV 无效")
    magic, total = struct.unpack_from("<HH", data, end)
    if magic != 0x6907 or total < 4 or end + total > len(data):
        raise HTTPException(422, "MCUboot TLV 无效")
    digest = signature = signature_type = None
    position = end + 4
    while position < end + total:
        if position + 4 > end + total:
            raise HTTPException(422, "TLV 截断")
        kind, size = struct.unpack_from("<HH", data, position)
        position += 4
        if position + size > end + total:
            raise HTTPException(422, "TLV 越界")
        value = data[position:position + size]
        position += size
        if kind == 0x10:
            if digest is not None or size != 32:
                raise HTTPException(422, "镜像哈希无效")
            digest = value
        elif kind in (0x20, 0x22):
            if signature is not None:
                raise HTTPException(422, "签名重复")
            signature = value
            signature_type = kind
    if digest != hashlib.sha256(data[:end]).digest():
        raise HTTPException(422, "MCUboot 镜像哈希校验失败")
    verification, fingerprint = "untrusted", None
    if key_path.is_file() and signature:
        try:
            key_bytes = key_path.read_bytes()
            key = serialization.load_pem_public_key(key_bytes)
            if signature_type == 0x22 and isinstance(key, ec.EllipticCurvePublicKey) and isinstance(key.curve, ec.SECP256R1):
                key.verify(signature, digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
            elif signature_type == 0x20 and isinstance(key, rsa.RSAPublicKey) and key.key_size == 2048:
                key.verify(signature, digest, padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
                           utils.Prehashed(hashes.SHA256()))
            else:
                raise ValueError("unsupported key/signature combination")
            verification = "trusted"
            fingerprint = hashlib.sha256(key_bytes).hexdigest()
        except (ValueError, TypeError, InvalidSignature):
            pass
    major, minor, revision, build = struct.unpack_from("<BBHI", data, 20)
    return {"version": f"{major}.{minor}.{revision}+{build}", "image_hash": digest.hex(),
            "verification": verification, "trust_key_sha256": fingerprint,
            "signature_algorithm": {0x20: "rsa2048-pss-sha256", 0x22: "ecdsa-p256-sha256"}.get(signature_type)}


class FirmwareStore:
    def __init__(self, root):
        self.root = Path(root) / "firmware"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.key_path = self.root / "trusted-key.pem"
        with self.db() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS releases(id TEXT PRIMARY KEY,state TEXT NOT NULL,created REAL NOT NULL,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS upgrades(id TEXT PRIMARY KEY,owner TEXT NOT NULL,data TEXT NOT NULL);""")
        (self.root / "index.sqlite3").chmod(0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.root / "index.sqlite3", timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def release(row):
        return dict(json.loads(row["data"]), id=row["id"], state=row["state"], created=row["created"])

    def get(self, fid):
        if not re.fullmatch(r"[0-9a-f]{32}", fid):
            raise HTTPException(404, "固件不存在")
        with self.db() as db:
            row = db.execute("SELECT * FROM releases WHERE id=?", (fid,)).fetchone()
        if not row:
            raise HTTPException(404, "固件不存在")
        return self.release(row)

    def list(self, developer):
        with self.db() as db:
            return [self.release(row) for row in db.execute(
                "SELECT * FROM releases WHERE ? OR state='published' ORDER BY created DESC LIMIT 100", (developer,))]

    def import_image(self, data, filename, profile, author):
        if profile not in PROFILES or not re.fullmatch(r"[^/\\\x00-\x1f]{1,120}\.bin", filename):
            raise HTTPException(422, "请选择 profile 和 .bin 文件，文件名不能包含路径")
        info = inspect_image(data, self.key_path)
        if profile == "boa-dtls-ota-v1":
            if info["signature_algorithm"] != "rsa2048-pss-sha256":
                raise HTTPException(422, "Boa DTLS OTA 需要 RSA-2048 签名应用核")
            if len(data) > BOA_CLIP_OTA_MAX_SIZE:
                raise HTTPException(422, "应用核镜像超过 Boa Clip OTA 容量限制")
            info["boot_mode"] = "overwrite-only"
        fid = uuid.uuid4().hex
        info.update(filename=filename, profile_id=profile, size=len(data), sha256=hashlib.sha256(data).hexdigest(), author=author)
        path = self.root / (fid + ".bin")
        with path.open("xb") as output:
            output.write(data)
            output.flush()
            import os
            os.fsync(output.fileno())
        path.chmod(0o600)
        try:
            with self.db() as db:
                db.execute("INSERT INTO releases VALUES (?,?,?,?)", (fid, "draft", time.time(), json.dumps(info)))
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return self.get(fid)

    def trusted(self, row):
        return (row["verification"] == "trusted" and self.key_path.is_file()
                and hashlib.sha256(self.key_path.read_bytes()).hexdigest() == row["trust_key_sha256"])

    def change_state(self, fid, state):
        row = self.get(fid)
        if state == "published" and (row["state"] == "withdrawn" or not self.trusted(row)):
            raise HTTPException(409, "不能发布：已撤下或未通过可信公钥验签")
        with self.db() as db:
            db.execute("UPDATE releases SET state=? WHERE id=? AND state!='withdrawn'", (state, fid))
        return self.get(fid)

    def start(self, user, release_id, device_label):
        row = self.get(release_id)
        if (row["state"] != "published" or row["profile_id"] not in ("ble-standard", "boa-dtls-ota-v1") or not self.trusted(row)
                or (self.root / "demo-only").exists()):
            raise HTTPException(409, "当前版本/profile 不允许应用 OTA")
        item = {"id": uuid.uuid4().hex, "release_id": release_id, "device_label": device_label,
                "expected_image_hash": row["image_hash"], "created": time.time(), "state": "uploading",
                "evidence_source": "browser_report"}
        with self.db() as db:
            db.execute("INSERT INTO upgrades VALUES (?,?,?)", (item["id"], user, json.dumps(item)))
        return item

    def upgrades(self, user):
        with self.db() as db:
            return [json.loads(row[0]) for row in db.execute("SELECT data FROM upgrades WHERE owner=? ORDER BY rowid DESC LIMIT 100", (user,))]

    def update(self, user, uid, event):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM upgrades WHERE id=? AND owner=?", (uid, user)).fetchone()
            if not row:
                raise HTTPException(404, "记录不存在")
            item = json.loads(row[0])
            if item["state"] in ("succeeded", "failed"):
                raise HTTPException(409, "记录已结束")
            if item["state"] == "awaiting_reconnect" and event["state"] == "uploading":
                raise HTTPException(409, "待核实记录不能退回上传状态")
            if event["state"] == "succeeded" and not (
                item["state"] == "awaiting_reconnect" and event.get("active") is True
                and event.get("confirmed") is True and event.get("image_hash") == item["expected_image_hash"]):
                raise HTTPException(409, "缺少重连后的 active/confirmed 镜像哈希证据")
            item.update(event, updated=time.time())
            db.execute("UPDATE upgrades SET data=? WHERE id=? AND owner=?", (json.dumps(item), uid, user))
        return item
