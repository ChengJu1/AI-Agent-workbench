"""Uvicorn 入口；应用创建与路由分别在 application.py 和 api/ 中维护。"""
from app.application import create_app


app = create_app()
