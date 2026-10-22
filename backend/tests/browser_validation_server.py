"""Local-only acceptance harness, never imported by the workbench application.
Run from backend; open http://127.0.0.1:8087/ using CUA. Only synthetic data.
Public acceptance opens a fresh unauthenticated browser and only navigates to login.
"""
import html
import io
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, Response, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from app.models.tracking import TrackingDefinition
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
        if f'{urlsplit(url).scheme}://{urlsplit(url).netloc}' not in (allowed,'http://localhost:8087'):
            raise ServiceError('测试环境仅能访问本地合成申请表。', 403)
    class FixtureHttp:
        def __init__(self):self.static_requests=0
        def request(self, url, method='GET', headers=None, body=None, **kwargs):
            validate(url)
            if urlsplit(url).hostname == 'localhost':self.static_requests+=1
            result = httpx.request(method, url, headers=headers, content=body, follow_redirects=False, trust_env=False, timeout=10)
            return {'url': url, 'status': result.status_code, 'headers': list(result.headers.multi_items()), 'body': result.content}
    services.platform.browser = BrowserService(services.platform.files, http=FixtureHttp(), url_validator=validate, headless=os.getenv('WORKBENCH_VALIDATE_HEADED')!='1')
    agent = services.registry.create(CreateAgentRequest(name='本地合成验证', description='不属于真实投递', system_prompt='仅测试', platform_capabilities=['files', 'web', 'browser', 'tracking']))
    cid = services.store.create(agent.id)
    from docx import Document
    document = Document(); document.add_paragraph('Synthetic candidate. Python SQL. Local acceptance only.')
    raw = io.BytesIO(); document.save(raw)
    file = services.platform.files.upload(cid, 'synthetic-resume.docx', raw.getvalue())
    state = {'snapshot': None, 'pending': None, 'submissions': 0, 'business_status': '处理中'}
    local_file = directory / 'synthetic-linked.txt'
    local_file.write_text('Synthetic local resource v1', encoding='utf-8')
    services.platform.files.link_local(cid, str(local_file.resolve()))
    services.store.add_message(cid, 'user', '合成验收会话：文件版本与执行跟踪。')
    from contextlib import asynccontextmanager
    import asyncio
    @asynccontextmanager
    async def lifespan(app):
        await services.tracking.start()
        yield
        await services.tracking.close()
        await asyncio.to_thread(services.platform.browser.close)
    app = FastAPI(lifespan=lifespan)
    app.state.services = services
    from app.api import agents,conversations,actions,platform,tracking,builds
    for router in (agents.router,conversations.router,actions.router,platform.router,tracking.router,builds.router):
        app.include_router(router)
    dist = directory / 'tracking-ui-dist'
    app.mount('/assets', StaticFiles(directory=dist / 'assets'), name='assets')
    @app.get('/workbench')
    def workbench():
        return FileResponse(dist / 'index.html')
    @app.exception_handler(ServiceError)
    def errors(request, error):
        return JSONResponse({'detail': str(error)}, status_code=error.status_code)
    @app.get('/', response_class=HTMLResponse)
    def home():
        return '''<!doctype html><meta charset="utf-8"><title>基础能力 · 本地合成验收</title>
<style>body{font:15px/1.8 system-ui;max-width:1000px;margin:35px auto;color:#544260}button{padding:10px;margin:5px;border:1px solid #cbb7dc;background:#f8f3fc;border-radius:6px}pre{white-space:pre-wrap;background:#faf7fc;padding:20px}img{max-width:100%;border:1px solid #ddd}</style>
<h1>基础能力 · 本地合成验收</h1><p>默认操作本地合成申请表；公开岗位验收只导航到登录页，不输入个人资料，不向公司投递。</p>
<button onclick="run('open')">打开本地申请表</button><button onclick="run('prepare')">生成操作清单</button>
<button onclick="run('approve')">确认执行本地合成申请</button><button onclick="run('repeat')">验证重复确认被拒绝</button>
<button onclick="run('headers')">验证重复响应头与动态正文</button>
<button onclick="run('buttons-open')">读取自定义按钮合成页</button><button onclick="run('buttons-prepare')">生成自定义按钮确认清单</button><button onclick="run('buttons-approve')">确认点击本地合成按钮</button>
<p>空白登录页回归：仅导航，不填写任何资料。</p><button onclick="run('login-open')">打开导航验收页</button><button onclick="run('login-prepare')">生成登录导航清单</button><button onclick="run('login-approve')">确认导航到合成登录页</button>
<button onclick="run('cache-cold')">清空缓存对照：接手后刷新</button><button onclick="run('cache-warm')">保留缓存：接手后返回并刷新</button>
<p>预览与已登录投递导航合成回归：只做岗位校验，不提交。</p><button onclick="run('preview-open')">打开截图干扰验收</button><button onclick="run('preview-state')">检查页面样式变化次数</button><button onclick="run('preview-prepare')">生成合成岗位校验清单</button><button onclick="run('preview-approve')">确认合成校验并进入填写页</button>
<p>公开岗位到登录页验收：全新会话，不输入账号或个人资料，不投递。</p><button onclick="run('public-open')">打开公开岗位验收</button><button onclick="run('public-prepare')">接手交回后生成登录导航</button><button onclick="run('public-click')">仅点击进入公开登录页</button>
<p><a href="/workbench">打开隔离验收工作台</a></p><button onclick="run('tracking')">生成只读跟踪方案</button><button onclick="run('status')">模拟状态变为已结束</button><button onclick="run('file-change')">模拟本机文件修改</button><button onclick="run('file-move')">模拟本机文件改名</button><p id="status">等待开始</p><pre id="result"></pre><img id="preview" alt="受控浏览器预览" hidden>
<script>async function run(action){document.querySelectorAll('button').forEach(b=>b.disabled=true);try{let r=await fetch('/demo/'+action,{method:'POST'});let data=await r.json();document.getElementById('status').textContent=r.ok?'操作完成':'已阻止或失败';document.getElementById('result').textContent=JSON.stringify(data,null,2);let img=document.getElementById('preview');img.src='/demo/screenshot?t='+Date.now();img.hidden=false;}catch(e){document.getElementById('status').textContent=String(e)}finally{document.querySelectorAll('button').forEach(b=>b.disabled=false)}}</script>'''
    @app.get('/fixture', response_class=HTMLResponse)
    def fixture():
        return '''<!doctype html><meta charset="utf-8"><title>合成岗位申请表</title><h1>本地合成岗位申请</h1><p>Python / SQL 工程师 · 不是真实招聘</p>
<form action="/receipt" method="post" enctype="multipart/form-data"><p><label>姓名 <input name="candidate"></label></p>
<p><label>技能 <textarea name="skills"></textarea></label></p><p><label>简历 <input type="file" name="resume"></label></p>
<button type="submit">提交测试申请</button></form>'''
    @app.get('/login-start',response_class=HTMLResponse)
    def login_start():
        return '<!doctype html><meta charset="utf-8"><title>合成岗位页</title><script defer src="http://localhost:8087/job-ui.js"></script><body></body>'
    @app.get('/preview-fixture',response_class=HTMLResponse)
    def preview_fixture():
        return '''<!doctype html><meta charset="utf-8"><title>合成已登录岗位页</title><h1>合成账号 · 已登录</h1><p id="counter">样式变化：0；窗口尺寸变化：0</p><input placeholder="合成搜索框，不填写真实资料"><button onclick="fetch('/check-job',{method:'POST',body:'synthetic-job'}).then(r=>{if(r.ok)location.href='/application-form';})">立即投递（仅合成校验）</button><script>
let styles=0,resizes=0;const report=()=>document.querySelector('#counter').textContent='样式变化：'+styles+'；窗口尺寸变化：'+resizes;
new MutationObserver(()=>{styles++;report();}).observe(document.querySelector('input'),{attributes:true,attributeFilter:['style']});
window.addEventListener('resize',()=>{resizes++;report();});</script>'''
    @app.post('/check-job')
    def check_job():
        state['preflights']=state.get('preflights',0)+1
        return {'checked':True,'application_submitted':False}
    @app.get('/application-form',response_class=HTMLResponse)
    def application_form():
        return '<!doctype html><meta charset="utf-8"><h1>合成申请填写页</h1><p>岗位校验通过；没有提交申请。</p><label>合成姓名 <input name="candidate"></label>'
    @app.post('/demo/preview-open')
    def preview_open():
        state['snapshot']=services.platform.execute(cid,'browser_open',{'url':allowed+'/preview-fixture'})
        return {'page':state['snapshot']}
    @app.post('/demo/preview-state')
    def preview_state():
        sid=state['snapshot']['session_id'];browser=services.platform.browser
        return {'page':browser.call('read',cid,sid),'capture_time':browser.sessions[sid].get('capture',{}).get('captured_at'),'submissions':state['submissions'],'preflights':state.get('preflights',0)}
    @app.post('/demo/preview-prepare')
    def preview_prepare():
        snapshot=services.platform.browser.call('read',cid,state['snapshot']['session_id'])
        target=next(e for e in snapshot['elements'] if e['label']=='立即投递（仅合成校验）')
        state['pending']=services.platform.execute(cid,'browser_prepare_actions',{'session_id':snapshot['session_id'],'snapshot_id':snapshot['snapshot_id'],'operations':[{'kind':'click','element_id':target['id']}]})['pending_action']
        return {'pending_action':state['pending'],'submissions':state['submissions'],'preflights':state.get('preflights',0)}
    @app.post('/demo/preview-approve')
    def preview_approve():
        result=services.approvals.decide(state['pending']['id'],True)
        return {'status':result['status'],'page':result['result']['page'],'submissions':state['submissions'],'preflights':state.get('preflights',0)}
    @app.get('/job-ui.js')
    def job_ui():
        return Response("Promise.all([fetch('http://localhost:8087/site.json').then(r=>r.json()),fetch('http://localhost:8087/logo.svg').then(r=>r.text()),fetch('http://localhost:8087/view.html').then(r=>r.text())]).then(()=>{document.body.innerHTML='<h1>合成岗位页已加载</h1><a href=/login-empty>打开合成登录页</a>';});",media_type='application/javascript')
    @app.get('/view.html')
    def view_template():return HTMLResponse('<header>合成页头组件</header>',headers={'Access-Control-Allow-Origin':'*'})
    @app.get('/site.json')
    def site_config():return JSONResponse({'title':'仅本地合成配置'},headers={'Access-Control-Allow-Origin':'*'})
    @app.get('/logo.svg')
    def logo():return Response('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20" fill="purple"/></svg>',media_type='image/svg+xml',headers={'Access-Control-Allow-Origin':'*'})
    @app.get('/login-empty',response_class=HTMLResponse)
    def login_empty():
        return '<!doctype html><meta charset="utf-8"><title>合成登录页</title><script defer src="http://localhost:8087/login-ui.js"></script><body></body>'
    @app.get('/login-ui.js')
    def login_ui():
        return Response("document.body.innerHTML='<h1>合成登录页已加载</h1><p>跨站静态脚本已交付；没有填写或上传个人资料。</p><label>合成账号 <input aria-label=合成账号></label>';",media_type='application/javascript')
    @app.post('/demo/login-open')
    def login_open():
        state['snapshot']=services.platform.execute(cid,'browser_open',{'url':allowed+'/login-start'})
        return {'page':state['snapshot']}
    @app.post('/demo/login-prepare')
    def login_prepare():
        sid=state['snapshot']['session_id']
        services.platform.browser.call('takeover',cid,sid,True)
        services.platform.browser.call('takeover',cid,sid,False)
        snapshot=services.platform.browser.call('read',cid,sid)
        state['snapshot']=snapshot
        eid=next(e['id'] for e in snapshot['elements'] if e['label']=='打开合成登录页')
        state['pending']=services.platform.execute(cid,'browser_prepare_actions',{'session_id':snapshot['session_id'],'snapshot_id':snapshot['snapshot_id'],'operations':[{'kind':'click','element_id':eid}]})['pending_action']
        return {'pending_action':state['pending'],'submissions':state['submissions']}
    @app.post('/demo/login-approve')
    def login_approve():
        result=services.approvals.decide(state['pending']['id'],True)
        session=services.platform.browser.sessions[state['snapshot']['session_id']]
        return {'status':result['status'],'page':result['result']['page'],'has_sensitive_data':session.get('has_sensitive_data',False),'submissions':state['submissions']}
    def return_after_takeover(clear):
        sid=state['snapshot']['session_id'];browser=services.platform.browser;session=browser.sessions[sid]
        if clear:
            from app.platform.browser_resources import PublicResourceCache
            session['public_resources']=PublicResourceCache()
        before=browser.http.static_requests
        browser.call('takeover',cid,sid,True)
        browser.call('takeover',cid,sid,False)
        try:browser.call('observe',cid,sid,allowed+'/login-start')
        except ServiceError:pass
        page=browser.call('read',cid,sid)
        if not clear:
            page=browser.call('reload',cid,sid)
            assert page['text'].startswith('合成岗位页已加载')
            assert session['cached_resource_hits']>=8
        return {'cache_cleared':clear,'text':page['text'],'has_sensitive_data':session['has_sensitive_data'],
            'cached_resource_hits':session['cached_resource_hits'],'new_cross_site_requests':browser.http.static_requests-before,'submissions':state['submissions']}
    @app.post('/demo/cache-cold')
    def cache_cold():return return_after_takeover(True)
    @app.post('/demo/cache-warm')
    def cache_warm():return return_after_takeover(False)
    @app.post('/demo/public-open')
    def public_open():
        services.platform.browser.close()
        services.platform.browser=BrowserService(services.platform.files,headless=False)
        state['snapshot']=services.platform.execute(cid,'browser_open',{'url':'https://szkingdom.zhiye.com/campus/detail?jobAdId=da7cb700-c052-476e-bbde-6e36b896c04c'})
        return {'page':state['snapshot'],'submissions':state['submissions']}
    @app.post('/demo/public-prepare')
    def public_prepare():
        sid=state['snapshot']['session_id'];browser=services.platform.browser
        browser.call('takeover',cid,sid,True);browser.call('takeover',cid,sid,False)
        snapshot=browser.call('read',cid,sid);state['snapshot']=snapshot
        target=next(e for e in snapshot['elements'] if e['label'].strip()=='立即投递')
        state['pending']=services.platform.execute(cid,'browser_prepare_actions',{'session_id':sid,'snapshot_id':snapshot['snapshot_id'],'operations':[{'kind':'click','element_id':target['id']}]})['pending_action']
        return {'pending_action':state['pending'],'submissions':state['submissions']}
    @app.post('/demo/public-click')
    def public_click():
        result=services.approvals.decide(state['pending']['id'],True)
        return {'status':result['status'],'page':result['result']['page'],'submissions':state['submissions']}
    @app.get('/header-fixture', response_class=HTMLResponse)
    def header_fixture():
        return '<!doctype html><meta charset="utf-8"><title>重复响应头验收</title><script src="/header-fixture.js"></script><h1 id="proof">等待合成脚本</h1>'
    @app.get('/custom-buttons', response_class=HTMLResponse)
    def custom_buttons():
        hidden = '<a style="display:none" href="#">隐藏链接</a>' * 180
        return '<!doctype html><meta charset="utf-8"><title>自定义按钮验收</title>'+hidden+'''<h1>合成自定义按钮</h1>
<div style="display:inline-flex;cursor:pointer;padding:18px" onclick="document.querySelector('#counter').textContent='点击计数：1'"><span>框架按钮（合成）</span></div>
<div role="button" tabindex="0">语义按钮（合成）</div>
<span id="cursor" style="cursor:pointer">事件委托按钮（合成）</span>
<div role="button" aria-disabled="true">禁用按钮（合成）</div>
<p id="counter">点击计数：0</p><div>普通说明文字</div>
<script>document.querySelector('#cursor').addEventListener('click',()=>document.querySelector('#counter').textContent='点击计数：2');</script>'''
    @app.post('/demo/buttons-open')
    def buttons_open():
        snapshot = services.platform.execute(cid,'browser_open',{'url':allowed+'/custom-buttons'})
        state['custom_snapshot'] = snapshot
        return snapshot
    @app.post('/demo/buttons-prepare')
    def buttons_prepare():
        snapshot = services.platform.execute(cid,'browser_read',{'session_id':state['custom_snapshot']['session_id']})
        target = next(e for e in snapshot['elements'] if e['label'] == '框架按钮（合成）')
        prepared = services.platform.execute(cid,'browser_prepare_actions',{'session_id':snapshot['session_id'],'snapshot_id':snapshot['snapshot_id'],'operations':[{'kind':'click','element_id':target['id']}]})
        state['custom_pending'] = prepared['pending_action']
        return {'page_before_confirmation':snapshot['text'],'pending_action':prepared['pending_action']}
    @app.post('/demo/buttons-approve')
    def buttons_approve():
        result = services.approvals.decide(state['custom_pending']['id'],True)
        return {'status':result['status'],'result':result['result']}
    @app.get('/header-fixture.js')
    def header_script():
        response = Response("document.addEventListener('DOMContentLoaded',()=>document.getElementById('proof').textContent='合成脚本正文已加载');",media_type='application/javascript')
        response.raw_headers.extend([(b'Vary',b'Accept-Encoding'),(b'vary',b'Accept-Encoding')])
        return response
    @app.post('/demo/headers')
    def headers_check():
        snapshot = services.platform.execute(cid,'browser_open',{'url':allowed+'/header-fixture'})
        return {'dynamic_content_verified':'合成脚本正文已加载' in snapshot['text'],'page':snapshot}
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
    @app.get('/application-status', response_class=HTMLResponse)
    def application_status():
        return '<meta charset="utf-8"><title>合成申请状态</title><div id="application">申请 TEST-RECEIPT-1 '+state['business_status']+'</div>'
    @app.post('/demo/status')
    def status_change():
        state['business_status'] = '已结束'
        return {'business_status':state['business_status'],'submissions':state['submissions']}
    @app.post('/demo/tracking')
    def propose_tracking():
        if not state['snapshot'] or not state['pending']:
            raise ServiceError('请先完成合成申请。',409)
        return services.tracking.create(cid,TrackingDefinition(title='合成申请持续跟踪',url=allowed+'/application-status',mode='browser',session_id=state['snapshot']['session_id'],selector='#application',anchor='TEST-RECEIPT-1',interval_minutes=5,record_id='run_'+state['pending']['id'],rules=[{'status':'处理中','keywords':['处理中']},{'status':'已结束','keywords':['已结束'],'terminal':True}]))
    @app.post('/demo/file-change')
    def change_local():
        local_file.write_text('Synthetic local resource v2',encoding='utf-8')
        return {'changed':True,'path':str(local_file.resolve())}
    @app.post('/demo/file-move')
    def move_local():
        moved=local_file.with_name('synthetic-renamed.txt')
        local_file.rename(moved)
        return {'moved':True,'new_path':str(moved.resolve())}
    @app.get('/demo/screenshot')
    def screenshot():
        if not state['snapshot']: return Response(status_code=404)
        return Response(services.platform.browser.call('screenshot', cid, state['snapshot']['session_id']), media_type='image/png')
    return app


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(create_validation_app(), host='127.0.0.1', port=8087, log_level='warning')
