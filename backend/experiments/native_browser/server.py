"""Attended local experiment. No imports or changes to the production application.

Run with backend/.venv/bin/python backend/experiments/native_browser/server.py.
All browser interactions originate from the explicit buttons on the local page.
"""
import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import timedelta
import json
import os
from pathlib import Path
import secrets
import shutil

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from starlette.middleware.trustedhost import TrustedHostMiddleware
import uvicorn

from policy import BASE, MCP_VERSION, command, network_summary

HERE = Path(__file__).resolve().parent
DATA = HERE.parents[1] / 'data/platform-validation/native-browser-mcp'
CLI = DATA / 'node_modules/@playwright/mcp/cli.js'
NONCE = secrets.token_urlsafe(32)


def create_app():
    state = {'client': None, 'lock': asyncio.Lock(), 'options_reads': 0,
             'submissions': 0, 'calls': [], 'screen': None}

    @asynccontextmanager
    async def lifespan(app):
        if not CLI.is_file():
            raise RuntimeError(f'请先安装 @playwright/mcp@{MCP_VERSION}，见本目录 README。')
        DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
        profile = DATA / 'profile'
        profile.mkdir(exist_ok=True, mode=0o700)
        output = DATA / 'output'
        output.mkdir(exist_ok=True, mode=0o700)
        config = DATA / 'config.json'
        config.write_text(json.dumps({
            'browser': {'browserName': 'chromium', 'userDataDir': str(profile),
                        'launchOptions': {'channel': 'chrome', 'headless': False,
                                          'chromiumSandbox': True}},
            'outputDir': str(output), 'saveSession': False,
            'snapshot': {'mode': 'none'}, 'console': {'level': 'error'},
            'codegen': 'none', 'timeouts': {'navigation': 30000, 'action': 5000},
        }), encoding='utf-8')
        node = shutil.which('node')
        if not node:
            raise RuntimeError('需要 Node.js 18 或更新版本。')
        params = StdioServerParameters(command=node, cwd=str(DATA),
            args=[str(CLI), '--config', str(config), '--no-webmcp'],
            env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'en_US.UTF-8'})
        # No browser requests, cookies or MCP responses in this process log.
        with (DATA / 'mcp-stderr.log').open('a', encoding='utf-8') as errlog:
            async with stdio_client(params, errlog=errlog) as streams:
                async with ClientSession(streams[0], streams[1]) as client:
                    await client.initialize()
                    available = {t.name for t in (await client.list_tools()).tools}
                    needed = {command(n)[0] for n in ('open-job', 'read', 'screen', 'diagnostics', 'close')}
                    if not needed <= available:
                        raise RuntimeError('官方 MCP 缺少实验所需工具。')
                    state['client'] = client
                    yield
                    state['client'] = None

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])

    @app.middleware('http')
    async def local_only(request: Request, next_call):
        if request.url.path.startswith('/api/'):
            if request.headers.get('x-workbench-probe') != NONCE:
                return JSONResponse({'detail': '请从本地实验页面操作。'}, status_code=403)
            if request.headers.get('origin') not in (None, BASE):
                return JSONResponse({'detail': '不接受其他网站的操作。'}, status_code=403)
        response = await next_call(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'none'"
        return response

    @app.get('/', response_class=HTMLResponse)
    def home():
        return (HERE / 'index.html').read_text(encoding='utf-8').replace('__NONCE__', NONCE)

    @app.post('/api/{action}')
    async def perform(action: str):
        try:
            tool, args = command(action)
        except ValueError as error:
            raise HTTPException(403, str(error)) from error
        if state['lock'].locked():
            raise HTTPException(409, '正在操作，请等待结果；不会排队重试。')
        async with state['lock']:
            state['calls'].append(action)
            try:
                result = await state['client'].call_tool(tool, args, read_timeout_seconds=timedelta(seconds=45))
            except Exception:
                # Never retry a browser command on a timeout.
                raise HTTPException(502, '工具未完成；请查看独立窗口，不自动重试。') from None
            text = '\n'.join(c.text for c in result.content if c.type == 'text')
            if action == 'diagnostics':
                return {'is_error': bool(result.isError), 'requests': network_summary(text),
                        'fixture_options_reads': state['options_reads'], 'fixture_submissions': state['submissions']}
            if action == 'screen':
                images = [c for c in result.content if c.type == 'image']
                if images:
                    state['screen'] = (base64.b64decode(images[0].data), images[0].mimeType)
                return {'is_error': bool(result.isError), 'has_image': bool(images)}
            # Snapshot remains in the local page; do not write it into application storage.
            return {'is_error': bool(result.isError), 'text': text[:65000],
                    'fixture_options_reads': state['options_reads'], 'fixture_submissions': state['submissions']}

    @app.get('/api/screen')
    def screenshot():
        if state['screen'] is None:
            raise HTTPException(404, '尚未手动获取画面。')
        content, mime = state['screen']
        return Response(content=content, media_type=mime)

    @app.get('/fixture', response_class=HTMLResponse)
    def fixture():
        return '''<!doctype html><meta charset="utf-8"><title>正常浏览器·合成表单</title>
<h1>合成表单：仅用于架构验证</h1><p id="visits"></p><p id="state">等待初始化</p>
<div id="fields"></div><script src="http://localhost:8088/fixture/dependency.js"></script>
<script>const n=Number(localStorage.getItem('probe-visits')||0)+1;
localStorage.setItem('probe-visits',n);document.querySelector('#visits').textContent='专用配置访问次数：'+n;
fetch('/fixture/options',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:'synthetic-options'})})
.then(r=>r.json()).then(data=>{document.querySelector('#fields').innerHTML='<label>合成姓名 <input name="name"></label><label>合成岗位 <select><option>'+data.option+'</option></select></label>';
document.querySelector('#state').textContent=window.probeDependency?'POST 查询与跨域脚本均完成，表单可用':'依赖未就绪';});</script>'''

    @app.get('/fixture/dependency.js')
    def dependency():
        return Response('window.probeDependency=true;', media_type='text/javascript')

    @app.post('/fixture/options')
    def options():
        state['options_reads'] += 1
        return {'option': 'Python 工程师（合成）'}

    @app.post('/fixture/submit')
    def submit():
        state['submissions'] += 1
        raise HTTPException(403, '本实验不提供提交功能。')

    return app


if __name__ == '__main__':
    uvicorn.run(create_app(), host='127.0.0.1', port=8088, access_log=False)
