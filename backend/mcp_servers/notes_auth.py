"""个人本地服务的固定 Bearer 令牌校验；不提供 OAuth 登录流程。"""
import hmac
import os

from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse


class NotesBearerMiddleware:
    def __init__(self, app, token):
        self.app = app
        self.expected = token.encode("ascii")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        values = [value for key, value in scope["headers"] if key.lower() == b"authorization"]
        scheme, _, token = values[0].partition(b" ") if len(values) == 1 else (b"", b"", b"")
        if scheme.lower() != b"bearer" or not hmac.compare_digest(token, self.expected):
            response = JSONResponse({"detail": "需要有效的笔记 MCP 访问令牌。"}, status_code=401,
                                    headers={"WWW-Authenticate": 'Bearer realm="local_notes"'})
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)


class NotesMCP(FastMCP):
    def streamable_http_app(self):
        token = os.getenv("NOTES_MCP_TOKEN", "")
        if len(token) < 32 or not token.isascii() or any(char.isspace() for char in token):
            raise ValueError("HTTP 服务需要 NOTES_MCP_TOKEN：至少 32 位的随机 ASCII 令牌，不能包含空白。")
        app = super().streamable_http_app()
        app.add_middleware(NotesBearerMiddleware, token=token)
        return app
