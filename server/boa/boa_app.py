"""One Boa service: private App storage, DTLS receive and unified file listing."""

import asyncio
import secrets
import threading
from contextlib import asynccontextmanager


from server.storage.app import create_app as create_audio_app
from server.storage.app import parse_range
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from server.boa.registry import Registry
from server.boa.web_sessions import WebSessions


def user_token(headers):
    header = headers.get("authorization", "")
    return header[7:] if header.startswith("Bearer ") else ""


class BoaService:
    def __init__(self, root, dtls=None, allow_id_login=False):
        self.registry = Registry(root)
        self.sessions = WebSessions(self.registry, allow_id_login)
        self.tenants = {}
        self.lock = threading.RLock()

        @asynccontextmanager
        async def lifespan(app):
            stop_dtls = dtls(self.registry) if dtls else None

            async def sweep():
                while True:
                    await asyncio.sleep(30)
                    try:
                        await asyncio.to_thread(self.registry.reconcile)
                        for tenant, _ in list(self.tenants.values()):
                            await asyncio.to_thread(tenant.state.store.cleanup)
                    except OSError:
                        import logging

                        logging.getLogger(__name__).error("File reconciliation pending")

            task = asyncio.create_task(sweep())
            try:
                yield
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                if stop_dtls:
                    await asyncio.to_thread(stop_dtls)

        self.api = FastAPI(
            docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
        )
        from server.boa.firmware_web import install_firmware_web

        install_firmware_web(self.api, self.registry, self.sessions)
        self.sessions.install(self.api)
        from server.boa.device_configurations import install_device_configurations

        install_device_configurations(self.api, self.registry, self.sessions)

        def owner(request):
            user, _ = self.sessions.principal(request)
            if user is None:
                raise HTTPException(401, "Unauthorized")
            return user

        @self.api.get("/api/boa/v1/health")
        def health():
            return JSONResponse(
                {"service": "boa", "status": "ok"},
                headers={"Cache-Control": "no-store"},
            )

        @self.api.get("/api/boa/v1/audio-files")
        def listing(request: Request, offset: int = 0, limit: int = 50):
            user = owner(request)
            if offset < 0 or not 1 <= limit <= 100:
                raise HTTPException(422, "Invalid pagination")
            audio, _ = self.tenant(user)
            with audio.state.store.db() as db:
                rows = [
                    dict(row, source="app_upload")
                    for row in db.execute(
                        "SELECT * FROM uploads WHERE state='complete'"
                    )
                ]
            rows.extend(self.registry.clip_files(user))
            rows.sort(key=lambda row: (row["created"], row["id"]), reverse=True)
            return {"items": rows[offset : offset + limit]}

        @self.api.api_route(
            "/api/boa/v1/audio-files/{fid}/content", methods=["GET", "HEAD"]
        )
        def raw_content(fid: str, request: Request):
            user = owner(request)
            row = self.registry.raw_file(user, fid)
            if not row:
                raise HTTPException(404, "File not found")
            path = self.registry.raw_path(row)
            if not path.is_file():
                raise HTTPException(404, "File unavailable")
            size, etag = row["size"], '"' + row["sha256"] + '"'
            start, end, status = 0, size - 1, 200
            if (
                request.headers.get("range")
                and request.headers.get("if-range", etag) == etag
            ):
                start, end = parse_range(request.headers["range"], size)
                status = 206
            headers = {
                "Content-Length": str(end - start + 1),
                "Accept-Ranges": "bytes",
                "ETag": etag,
                "Content-Type": "application/octet-stream",
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            }
            if status == 206:
                headers["Content-Range"] = f"bytes {start}-{end}/{size}"
            if request.method == "HEAD":
                return Response(status_code=status, headers=headers)

            def stream():
                with path.open("rb") as source:
                    source.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        block = source.read(min(65536, remaining))
                        if not block:
                            break
                        remaining -= len(block)
                        yield block

            return StreamingResponse(stream(), status_code=status, headers=headers)

    def tenant(self, user):
        with self.lock:
            if user not in self.tenants:
                internal = secrets.token_urlsafe(40)
                audio = create_audio_app(
                    self.registry.root / "users" / user / "audio", internal
                )
                self.tenants[user] = audio, internal
            return self.tenants[user]

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith("/api/audio/"):
            try:
                user, _ = self.sessions.principal(Request(scope))
            except HTTPException as exc:
                return await JSONResponse({'detail': exc.detail}, status_code=exc.status_code)(
                    scope, receive, send
                )
            if user is None:
                return await JSONResponse({"detail": "Unauthorized"}, status_code=401)(
                    scope, receive, send
                )
            audio, internal = self.tenant(user)
            scoped = dict(scope)
            scoped["headers"] = [
                (key, value)
                for key, value in scope["headers"]
                if key != b"authorization"
            ] + [(b"authorization", f"Bearer {internal}".encode())]
            return await audio(scoped, receive, send)
        return await self.api(scope, receive, send)


def create_app(root, dtls=None, allow_id_login=False):
    return BoaService(root, dtls, allow_id_login)
