"""创建 FastAPI 应用；服务和数据库仅在 lifespan 启动阶段初始化。"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.api import actions, agents, conversations, evaluations, knowledge, mcp, skills
from app.config import Settings
from app.container import build_services
from app.errors import ServiceError


logger = logging.getLogger(__name__)


def create_app(settings=None, services=None):
    if settings is None:
        settings = Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        if app.state.services is None:
            app.state.services = await run_in_threadpool(build_services, settings)
        yield

    app = FastAPI(title="AI Agent Workbench", lifespan=lifespan)
    app.state.services = services
    app.add_middleware(
        CORSMiddleware, allow_origins=list(settings.cors_origins),
        allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
    )

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, error: ServiceError):
        return JSONResponse(status_code=error.status_code, content={"detail": str(error)})

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
    return app
