"""Experimental same-origin Web console; stable firmware draft API is untouched."""

import asyncio
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from server.boa.firmware_store import MAX_SIZE, PROFILES, FirmwareStore
from pydantic import BaseModel, Field
from starlette.staticfiles import StaticFiles

API = "/api/boa/experimental/firmware"
WEB_ROOT = Path(__file__).resolve().parents[2] / "server/web"


class UpgradeStart(BaseModel):
    release_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    device_label: str = Field(min_length=1, max_length=100)


class UpgradeEvent(BaseModel):
    state: Literal["uploading", "awaiting_reconnect", "succeeded", "failed"]
    image_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    active: bool | None = None
    confirmed: bool | None = None
    error: str | None = Field(default=None, max_length=240)


class ConsoleFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers.update({
            "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; media-src 'self' blob:; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
            "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer", "Permissions-Policy": "bluetooth=(self)",
        })
        return response


def install_firmware_web(app, registry, sessions=None):
    store = FirmwareStore(registry.root)
    upload_lock = asyncio.Lock()

    def principal(request, developer=False):
        token = request.headers.get("authorization", "")
        user, cookie = sessions.principal(request) if sessions else (
            registry.user_for_token(token[7:] if token.startswith("Bearer ") else ""), False)
        if user is None:
            raise HTTPException(401, "Unauthorized")
        role = 'user' if cookie else registry.role(user)
        if developer and role != "developer":
            raise HTTPException(403, "需要开发者权限")
        return user, role

    @app.get(API + "/capabilities")
    def capabilities(request: Request):
        user, role = principal(request)
        return {"protocol_version": "firmware-web-prototype.1", "user_id": user, "role": role,
                "max_size_bytes": MAX_SIZE, "profiles": PROFILES, "remote_ota": False,
                "demo_mode": (store.root / "demo-only").exists(),
                "trusted_key_configured": store.key_path.is_file()}

    @app.get(API + "/releases")
    def releases(request: Request):
        _, role = principal(request)
        return {"items": store.list(role == "developer")}

    @app.post(API + "/releases", status_code=201)
    async def upload(request: Request, filename: str = "", profile_id: str = ""):
        user, _ = principal(request, developer=True)
        try:
            length = int(request.headers.get("content-length", "0"))
        except ValueError:
            raise HTTPException(400, "Invalid Content-Length")
        if length > MAX_SIZE:
            raise HTTPException(413, "固件超过 8 MiB")
        if upload_lock.locked():
            raise HTTPException(429, "已有导入任务，请稍后重试")
        async with upload_lock:
            data = bytearray()
            async for chunk in request.stream():
                if len(data) + len(chunk) > MAX_SIZE:
                    raise HTTPException(413, "固件超过 8 MiB")
                data.extend(chunk)
            return await asyncio.to_thread(store.import_image, bytes(data), filename, profile_id, user)

    @app.post(API + "/releases/{fid}/publish")
    def publish(fid: str, request: Request):
        principal(request, developer=True)
        return store.change_state(fid, "published")

    @app.post(API + "/releases/{fid}/withdraw")
    def withdraw(fid: str, request: Request):
        principal(request, developer=True)
        return store.change_state(fid, "withdrawn")

    @app.api_route(API + "/releases/{fid}/content", methods=["GET", "HEAD"])
    def content(fid: str, request: Request):
        _, role = principal(request)
        row = store.get(fid)
        if row["state"] == "withdrawn":
            raise HTTPException(410, "固件已撤下")
        if row["state"] != "published" and role != "developer":
            raise HTTPException(404, "固件不存在")
        return FileResponse(store.root / (fid + ".bin"), media_type="application/octet-stream",
                            filename=f"boa-{row['version']}.bin",
                            headers={"ETag": '"' + row["sha256"] + '"', "Cache-Control": "no-store"})

    @app.post(API + "/upgrades", status_code=201)
    def start(body: UpgradeStart, request: Request):
        user, _ = principal(request)
        return store.start(user, body.release_id, body.device_label)

    @app.get(API + "/upgrades")
    def upgrades(request: Request):
        user, _ = principal(request)
        return {"items": store.upgrades(user)}

    @app.patch(API + "/upgrades/{uid}")
    def event(uid: str, body: UpgradeEvent, request: Request):
        user, _ = principal(request)
        return store.update(user, uid, body.model_dump(exclude_none=True))

    app.mount("/firmware", ConsoleFiles(directory=WEB_ROOT, html=True, check_dir=False))
