"""创建 FastAPI 应用；服务和数据库仅在 lifespan 启动阶段初始化。"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.api import access, actions, agents, conversations, evaluations, knowledge, mcp, skills, builds, platform, tracking
from app.config import Settings
from app.container import build_services
from app.errors import ServiceError
from app.kits.registry import kits
from app.services.backup import run_daily


logger = logging.getLogger(__name__)


def create_app(settings=None, services=None):
    if settings is None:
        settings = Settings() if services is not None else Settings.from_env()
    access.check_exposure(settings)

    @asynccontextmanager
    async def lifespan(app):
        backup_task = None
        if app.state.services is None:
            app.state.services = await run_in_threadpool(build_services, settings)
            # Only the app's own database is backed up; injected services (tests) never touch it.
            if settings.backup_keep:
                directory = settings.backup_directory or settings.database_path.parent / "backups"
                backup_task = asyncio.create_task(run_daily(settings.database_path, directory, settings.backup_keep))
        if hasattr(app.state.services, "tracking"):
            await app.state.services.tracking.start()
        try:
            yield
        finally:
            if backup_task:
                backup_task.cancel()
            if hasattr(app.state.services, "tracking"):
                await app.state.services.tracking.close()
            if hasattr(app.state.services, "platform"):
                await run_in_threadpool(app.state.services.platform.browser.close)

    app = FastAPI(title="AI Agent Workbench", lifespan=lifespan)
    app.state.services = services
    access.install(app, settings)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.trusted_hosts))
    app.add_middleware(
        CORSMiddleware, allow_origins=list(settings.cors_origins),
        allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
    )

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, error: ServiceError):
        return JSONResponse(status_code=error.status_code, content=error.payload())

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception):
        logger.exception("接口执行失败: path=%s", request.url.path)
        return JSONResponse(status_code=500, content={"detail": "服务暂时不可用，请稍后重试。"})

    app.include_router(agents.router)
    app.include_router(conversations.router)
    app.include_router(actions.router)
    app.include_router(mcp.router)
    app.include_router(knowledge.router)
    app.include_router(evaluations.router)
    app.include_router(skills.router)
    app.include_router(builds.router)
    app.include_router(platform.router)
    app.include_router(tracking.router)
    for kit in kits():
        app.include_router(kit.router)
    return app
