"""Web listener with same-origin API dispatch to the one shared Boa backend.

This adapter neither creates a registry nor starts backend lifecycle tasks.
ASGI dispatch keeps streaming uploads/downloads and authentication unchanged.
"""
from starlette.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class Frontend:
    def __init__(self, backend: ASGIApp):
        self.backend = backend

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] == 'lifespan':
            while True:
                event = await receive()
                if event['type'] == 'lifespan.startup':
                    await send({'type': 'lifespan.startup.complete'})
                elif event['type'] == 'lifespan.shutdown':
                    await send({'type': 'lifespan.shutdown.complete'})
                    return
        if scope['type'] == 'http':
            path = scope['path']
            if path == '/':
                await RedirectResponse('/firmware/#recordings')(scope, receive, send)
                return
            if path.startswith(('/api/', '/firmware/')) or path == '/firmware':
                await self.backend(scope, receive, send)
                return
            await JSONResponse({'detail': 'Not Found'}, status_code=404)(scope, receive, send)
        elif scope['type'] == 'websocket':
            await send({'type': 'websocket.close', 'code': 1008})
