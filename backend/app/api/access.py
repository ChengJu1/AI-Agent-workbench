"""Optional access token. Off by default; required before the API is reachable from other machines."""
import hmac

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

COOKIE = "workbench_session"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "testserver", "backend"}
OPEN_PATHS = {"/api/health", "/api/session"}


class SessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=500)


def check_exposure(settings):
    """Refuse to serve non-local hosts without a token: the database holds personal data."""
    remote = [host for host in settings.trusted_hosts if host not in LOCAL_HOSTS]
    if remote and not settings.access_token:
        raise RuntimeError(f"WORKBENCH_TRUSTED_HOSTS 包含非本机地址（{', '.join(remote)}），请先设置 WORKBENCH_ACCESS_TOKEN。")


def install(app, settings):
    router = APIRouter(prefix="/api")  # Per app: each app has its own settings.

    @app.middleware("http")
    async def require_token(request: Request, call_next):
        token = settings.access_token
        if (not token or request.method == "OPTIONS" or not request.url.path.startswith("/api/")
                or request.url.path in OPEN_PATHS):
            return await call_next(request)
        header = request.headers.get("authorization", "")
        offered = header[7:] if header.lower().startswith("bearer ") else request.cookies.get(COOKIE, "")
        if offered and hmac.compare_digest(offered.encode(), token.encode()):
            return await call_next(request)
        return JSONResponse(status_code=401, content={"detail": "需要访问令牌。", "error_code": "AUTH_REQUIRED"})

    @router.post("/session")
    def open_session(body: SessionRequest):
        if not settings.access_token:
            return {"required": False}
        if not hmac.compare_digest(body.token.encode(), settings.access_token.encode()):
            return JSONResponse(status_code=401, content={"detail": "访问令牌不正确。", "error_code": "AUTH_REQUIRED"})
        response = JSONResponse({"required": True})
        # HttpOnly so page scripts never see it; plain links (calendar download) still carry it.
        response.set_cookie(COOKIE, body.token, max_age=30 * 86400, httponly=True, samesite="strict", path="/")
        return response

    @router.delete("/session")
    def close_session():
        response = Response(status_code=204)
        response.delete_cookie(COOKIE, path="/")
        return response

    app.include_router(router)
