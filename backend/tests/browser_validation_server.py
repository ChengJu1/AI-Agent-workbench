"""Local-only acceptance harness, never imported by the workbench application.
Run from backend; open http://127.0.0.1:8087/ using CUA. Only synthetic data.
"""
import html
import io
from pathlib import Path
import sys
from urllib.parse import urlsplit
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, Response, JSONResponse
from app.config import Settings
from app.container import build_services
from app.errors import ServiceError
from app.models.api import CreateAgentRequest
from app.platform.browser import BrowserService


def create_validation_app():
    directory = Path(__file__).resolve().parents[1] / 'data/platform-validation'
    directory.mkdir(exist_ok=True)
    services = build_services(Settings(database_path=directory / f'browser-{uuid4().hex}.db'))
    allowed = 'http://127.0.0.1:8087'
    def validate(url):
        if f'{urlsplit(url).scheme}://{urlsplit(url).netloc}' != allowed:
            raise ServiceError('测试环境仅能访问本地合成申请表。', 403)
    class FixtureHttp:
        def request(self, url, method='GET', headers=None, body=None, **kwargs):
            validate(url)
            result = httpx.request(method, url, headers=headers, content=body, follow_redirects=False, trust_env=False, timeout=10)
            return {'url': url, 'status': result.status_code, 'headers': list(result.headers.multi_items()), 'body': result.content}
    services.platform.browser = BrowserService(services.platform.files, http=FixtureHttp(), url_validator=validate, headless=True)
    agent = services.registry.create(CreateAgentRequest(name='本地合成验证', description='不属于真实投递', system_prompt='仅测试', platform_capabilities=['files', 'web', 'browser']))
    cid = services.store.create(agent.id)
    from docx import Document
    document = Document(); document.add_paragraph('Synthetic candidate. Python SQL. Local acceptance only.')
    raw = io.BytesIO(); document.save(raw)
    file = services.platform.files.upload(cid, 'synthetic-resume.docx', raw.getvalue())
    state = {'snapshot': None, 'pending': None, 'submissions': 0}
    from contextlib import asynccontextmanager
    import asyncio
    @asynccontextmanager
    async def lifespan(app):
        yield
        await asyncio.to_thread(services.platform.browser.close)
    app = FastAPI(lifespan=lifespan)
    @app.exception_handler(ServiceError)
    def errors(request, error):
        return JSONResponse({'detail': str(error)}, status_code=error.status_code)
    @app.get('/', response_class=HTMLResponse)
    def home():
        return '''<!doctype html><meta charset="utf-8"><title>基础能力 · 本地合成验收</title>
<style>body{font:15px/1.8 system-ui;max-width:1000px;margin:35px auto;color:#544260}button{padding:10px;margin:5px;border:1px solid #cbb7dc;background:#f8f3fc;border-radius:6px}pre{white-space:pre-wrap;background:#faf7fc;padding:20px}img{max-width:100%;border:1px solid #ddd}</style>
<h1>基础能力 · 本地合成验收</h1><p>只操作 127.0.0.1 上的合成申请表，不向任何公司投递。确认前不会填写或上传。</p>
<button onclick="run('open')">打开本地申请表</button><button onclick="run('prepare')">生成操作清单</button>
<button onclick="run('approve')">确认执行本地合成申请</button><button onclick="run('repeat')">验证重复确认被拒绝</button>
<p id="status">等待开始</p><pre id="result"></pre><img id="preview" alt="受控浏览器预览" hidden>
<script>async function run(action){document.querySelectorAll('button').forEach(b=>b.disabled=true);try{let r=await fetch('/demo/'+action,{method:'POST'});let data=await r.json();document.getElementById('status').textContent=r.ok?'操作完成':'已阻止或失败';document.getElementById('result').textContent=JSON.stringify(data,null,2);let img=document.getElementById('preview');img.src='/demo/screenshot?t='+Date.now();img.hidden=false;}catch(e){document.getElementById('status').textContent=String(e)}finally{document.querySelectorAll('button').forEach(b=>b.disabled=false)}}</script>'''
    @app.get('/fixture', response_class=HTMLResponse)
    def fixture():
        return '''<!doctype html><meta charset="utf-8"><title>合成岗位申请表</title><h1>本地合成岗位申请</h1><p>Python / SQL 工程师 · 不是真实招聘</p>
<form action="/receipt" method="post" enctype="multipart/form-data"><p><label>姓名 <input name="candidate"></label></p>
<p><label>技能 <textarea name="skills"></textarea></label></p><p><label>简历 <input type="file" name="resume"></label></p>
<button type="submit">提交测试申请</button></form>'''
    @app.post('/receipt', response_class=HTMLResponse)
    async def receipt(candidate: str = Form(...), skills: str = Form(...), resume: UploadFile = File(...)):
        await resume.read(); state['submissions'] += 1
        return f'<meta charset="utf-8"><title>合成申请回执</title><h1>TEST-RECEIPT-{state["submissions"]}</h1><p>本地合成申请已接收</p><p>{html.escape(candidate)} · {html.escape(skills)} · {html.escape(resume.filename or "")}</p>'
    @app.post('/demo/open')
    def open_page():
        state['snapshot'] = services.platform.execute(cid, 'browser_open', {'url': allowed+'/fixture'})
        return {'page': state['snapshot'], 'submissions': state['submissions']}
    @app.post('/demo/prepare')
    def prepare():
        snapshot = state['snapshot']
        if snapshot is None: raise ServiceError('请先打开页面。', 409)
        def element(label):
            return next(item['id'] for item in snapshot['elements'] if item['label'].strip() == label)
        operations = [{'kind': 'fill', 'element_id': element('姓名'), 'value': '合成候选人'},
                      {'kind': 'fill', 'element_id': element('技能'), 'value': 'Python / SQL；仅本地验收'},
                      {'kind': 'upload', 'element_id': element('简历'), 'file_id': file['id']},
                      {'kind': 'click', 'element_id': element('提交测试申请')}]
        result = services.platform.execute(cid, 'browser_prepare_actions', {'session_id': snapshot['session_id'], 'snapshot_id': snapshot['snapshot_id'], 'operations': operations})
        state['pending'] = result['pending_action']
        return {'pending_action': result['pending_action'], 'submissions_before_confirmation': state['submissions']}
    @app.post('/demo/approve')
    def approve():
        if not state['pending']: raise ServiceError('请先生成清单。', 409)
        result = services.approvals.decide(state['pending']['id'], True)
        return {'status': result['status'], 'result': result['result'], 'submissions': state['submissions']}
    @app.post('/demo/repeat')
    def repeat():
        try:
            services.approvals.decide(state['pending']['id'], True)
        except ServiceError as error:
            return {'duplicate_blocked': error.status_code == 409, 'submissions': state['submissions']}
        return {'duplicate_blocked': False, 'submissions': state['submissions']}
    @app.get('/demo/screenshot')
    def screenshot():
        if not state['snapshot']: return Response(status_code=404)
        return Response(services.platform.browser.call('screenshot', cid, state['snapshot']['session_id']), media_type='image/png')
    return app


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(create_validation_app(), host='127.0.0.1', port=8087, log_level='warning')
