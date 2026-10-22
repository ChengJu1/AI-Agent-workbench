"""从当前 FastAPI 应用中取得服务，不依赖可变的模块全局变量。"""
from fastapi import Request


def get_services(request: Request):
    return request.app.state.services
