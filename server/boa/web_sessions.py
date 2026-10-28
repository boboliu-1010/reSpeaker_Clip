"""Optional ID-only account selection for a trusted development network.

An ID is not proof of identity. These sessions never confer developer access.
"""
import hashlib
import secrets
import time

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

COOKIE = 'boa_session'
TTL = 7 * 24 * 60 * 60
PATH = '/api/boa/v1/session'


class Login(BaseModel):
    user_id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,32}$')


def same_origin(request):
    if request.headers.get('origin') != str(request.base_url).rstrip('/'):
        raise HTTPException(403, 'Same-origin request required')


class WebSessions:
    def __init__(self, registry, enabled=False):
        self.registry = registry
        self.enabled = enabled
        with registry.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS web_sessions '
                       '(digest TEXT PRIMARY KEY,user TEXT NOT NULL,expires INTEGER NOT NULL)')

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def cookie_user(self, request):
        token = request.cookies.get(COOKIE, '')
        if not self.enabled or len(token) != 43:
            return None
        with self.registry.db() as db:
            row = db.execute('SELECT users.id FROM web_sessions JOIN users '
                             'ON users.id=web_sessions.user WHERE digest=? AND expires>? '
                             'AND users.active=1', (self.digest(token), int(time.time()))).fetchone()
        return row['id'] if row else None

    def principal(self, request):
        header = request.headers.get('authorization')
        if header is not None:
            user = self.registry.user_for_token(header[7:] if header.startswith('Bearer ') else '')
            return user, False
        user = self.cookie_user(request)
        if user and request.method not in ('GET', 'HEAD', 'OPTIONS'):
            same_origin(request)
        if user and request.headers.get('x-boa-user') != user:
            raise HTTPException(409, 'session_user_changed')
        return user, True

    def revoke(self, request):
        token = request.cookies.get(COOKIE, '')
        if token:
            with self.registry.db() as db:
                db.execute('DELETE FROM web_sessions WHERE digest=?', (self.digest(token),))

    def install(self, app):
        @app.post(PATH)
        def login(body: Login, request: Request):
            if not self.enabled:
                raise HTTPException(403, 'ID login is not enabled')
            same_origin(request)
            token = secrets.token_urlsafe(32)
            now = int(time.time())
            with self.registry.db() as db:
                if not db.execute('SELECT id FROM users WHERE id=? AND active=1', (body.user_id,)).fetchone():
                    raise HTTPException(404, '用户 ID 尚未登记，请联系开发者')
                db.execute('DELETE FROM web_sessions WHERE expires<=?', (now,))
                db.execute('DELETE FROM web_sessions WHERE digest IN '
                           '(SELECT digest FROM web_sessions WHERE user=? ORDER BY expires DESC LIMIT -1 OFFSET 19)',
                           (body.user_id,))
                old = request.cookies.get(COOKIE, '')
                if old:
                    db.execute('DELETE FROM web_sessions WHERE digest=?', (self.digest(old),))
                db.execute('INSERT INTO web_sessions VALUES (?,?,?)',
                           (self.digest(token), body.user_id, now + TTL))
            response = JSONResponse({'user_id': body.user_id, 'role': 'user'},
                                    headers={'Cache-Control': 'no-store'})
            response.set_cookie(COOKIE, token, max_age=TTL, secure=request.url.scheme == 'https',
                                httponly=True, samesite='strict', path='/')
            return response

        @app.get(PATH)
        def current(request: Request):
            user = self.cookie_user(request)
            if not user:
                raise HTTPException(401, 'Not logged in')
            return JSONResponse({'user_id': user, 'role': 'user'}, headers={'Cache-Control': 'no-store'})

        @app.delete(PATH)
        def logout(request: Request):
            same_origin(request)
            user = self.cookie_user(request)
            if user and request.headers.get('x-boa-user') != user:
                raise HTTPException(409, 'session_user_changed')
            self.revoke(request)
            response = Response(status_code=204, headers={'Cache-Control': 'no-store'})
            response.delete_cookie(COOKIE, path='/', secure=request.url.scheme == 'https',
                                   httponly=True, samesite='strict')
            return response
