"""Isolated full-workbench acceptance for the native provider. Synthetic data only."""
from pathlib import Path
import os
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fastapi import Request
from fastapi.responses import HTMLResponse
import uvicorn
from browser_validation_server import create_validation_app
from app.platform.native_browser import NativeBrowserService
from app.models.api import CreateAgentRequest
from app.errors import ServiceError


def create_app():
    continuation = os.getenv('WORKBENCH_VALIDATE_CONTINUATION') == '1'
    tab_validation = os.getenv('WORKBENCH_VALIDATE_TABS') == '1'
    preview_validation = os.getenv('WORKBENCH_VALIDATE_PREVIEW') == '1'
    large_form_validation = os.getenv('WORKBENCH_VALIDATE_LARGE_FORM') == '1'
    if continuation:
        from app.config import Settings
        Settings.from_env()  # Existing model connection; isolated database remains below.
    app = create_validation_app()
    services = app.state.services
    if preview_validation or large_form_validation:
        class FixtureRuntime:
            async def stream_reply(self, *args, **kwargs):
                yield {'type': 'delta', 'content': '本机合成操作已完成；未连接招聘网站或真实模型。'}
        services.conversations.runtime = FixtureRuntime()
    browser = NativeBrowserService(services.platform.files, headless=False)
    browser.profile_root = Path(__file__).resolve().parents[1] / 'data/platform-validation/native-provider-profiles'
    def validate(url):
        if not url.startswith('http://127.0.0.1:8087/'):
            raise ServiceError('此验收只允许本机合成页面。', 403)
    browser.validate_url = validate
    services.platform.browser = browser
    agent = services.registry.create(CreateAgentRequest(name='原生浏览器合成验收', description='仅使用合成资料',
        system_prompt=('只操作本机合成申请表，不访问外部网站，不登录真实账号。用户已指定目标和资料：'
                       '在已打开的本机页面点击继续办理，填写姓名合成候选人、技能Python SQL，上传当前会话synthetic-resume.txt，'
                       '最后提交测试申请并核对合成回执。每批动作使用平台清单等待确认，最终提交单独审批。'
                       '用户接手后交回，由你继续这些步骤，不让用户手动填表。只询问实际缺失的字段。'
                       if continuation else '本地合成验收，不调用真实模型。'),
        platform_capabilities=['files', 'browser']))
    cid = services.store.create(agent.id)
    services.store.add_message(cid, 'user', '新方案合成验收：填写、文件版本、人工确认、执行台账。')
    file = services.platform.files.upload(cid, 'synthetic-resume.txt', b'Synthetic candidate. No real personal data.')
    state = {'style': 0, 'value': 0}

    @app.get('/large-form-host', response_class=HTMLResponse)
    def large_form_host():
        return '<!doctype html><meta charset="utf-8"><title>大表单与跨帧上传验收</title><h1>仅本机合成资料</h1><iframe title="合成大表单" src="/large-form-frame" style="width:95vw;height:800px"></iframe>'

    @app.get('/large-form-frame', response_class=HTMLResponse)
    def large_form_frame():
        fields = ''.join(f'<p><label>合成字段{i:04d} — 大表单分页验证<input name="field{i}"></label></p>' for i in range(900))
        return '''<!doctype html><meta charset="utf-8"><title>合成大表单</title><style>body{font:16px/1.8 system-ui;padding:20px}#upload{cursor:pointer;padding:25px;border:2px dashed purple}</style><h2>900 个字段之后的上传入口</h2>''' + fields + '''
<div id="upload"><img alt="icon/上传" src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'/%3E"><span>拖拽或点击上传合成简历</span><input id="file" type="file" hidden></div><p id="receipt">尚未上传</p>
<script>const file=document.querySelector('#file');document.querySelector('#upload').addEventListener('click',e=>{if(e.target!==file)file.click()});file.addEventListener('change',async()=>{const data=new FormData();data.append('file',file.files[0]);const r=await fetch('/large-upload',{method:'POST',body:data});const result=await r.json();document.querySelector('#receipt').textContent='合成解析回执：'+result.filename+'，'+result.bytes+' 字节';});</script>'''

    @app.post('/large-upload')
    async def large_upload(request: Request):
        form = await request.form()
        uploaded = form['file']
        content = await uploaded.read()
        state['upload_receipt'] = {'filename': uploaded.filename, 'bytes': len(content),
                                   'synthetic_content_matches': content == b'Synthetic candidate. No real personal data.'}
        return state['upload_receipt']

    @app.get('/preview-form', response_class=HTMLResponse)
    def preview_form():
        return '''<!doctype html><meta charset="utf-8"><title>预览与填写合成验收</title>
<style>body{font:18px/1.8 system-ui;padding:30px}.cosmetic{border-color:purple;outline-color:purple}input,textarea{margin:12px}</style>
<h1>本机合成表单</h1><p>仅验证预览和填写，不访问招聘网站。</p>
<form action="/receipt" method="post" enctype="multipart/form-data"><label>姓名<input name="candidate"></label><br>
<label>技能<textarea name="skills"></textarea></label><br><label>简历<input type="file" name="resume"></label><br>
<button>提交测试申请</button></form>
<script>let style=0,value=0;setInterval(async()=>{const s=await(await fetch('/preview-flags')).json();if(s.style!==style){style=s.style;const input=document.querySelector('input');input.classList.toggle('cosmetic');input.focus();}if(s.value!==value){value=s.value;document.querySelector('input').value='合成用户已修改';}},500)</script>'''

    @app.get('/preview-flags')
    def preview_flags():
        return {key: state[key] for key in ('style', 'value')}

    @app.get('/tab-fixture', response_class=HTMLResponse)
    def tab_fixture():
        return '<!doctype html><meta charset="utf-8"><title>已有填写页</title><label>姓名<input value="合成草稿，必须保留"></label><a href="about:blank" target="_blank">打开空白标签（合成测试）</a>'

    @app.get('/continuation-fixture', response_class=HTMLResponse)
    def continuation_fixture():
        # Delegated handler, generic div, no pointer cursor or onclick attribute.
        return '''<!doctype html><meta charset="utf-8"><title>交回续接合成验收</title>
<h1>合成资料验收，不连接招聘网站</h1><main><div id="next">继续办理</div></main>
<script>document.querySelector('main').addEventListener('click',e=>{if(e.target.id==='next'){
document.querySelector('main').innerHTML='<form method="POST" enctype="multipart/form-data" action="/receipt"><label>姓名<input name="candidate"></label><label>技能<textarea name="skills"></textarea></label><label>简历<input type="file" name="resume"></label><button>提交测试申请</button></form>';
}});</script>'''

    @app.get('/native', response_class=HTMLResponse)
    def home():
        return '''<!doctype html><meta charset="utf-8"><title>新浏览器·审批验收</title><style>body{font:15px/1.7 system-ui;margin:30px;color:#443453}button{padding:10px;margin:5px}pre{white-space:pre-wrap;max-height:500px;overflow:auto}</style>
<h1>官方 MCP → 工作台审批 → 合成回执</h1><p>只访问本机合成表，不登录真实账号。</p>
<button onclick="run('open')">打开合成表</button><button onclick="run('tab-prepare')">准备空白标签回归</button><button onclick="run('fill')">准备填写清单</button><button onclick="run('style')">切换焦点与样式（合成）</button><button onclick="run('change')">模拟用户修改字段（合成）</button><button onclick="run('upload')">准备上传清单</button><button onclick="run('submit')">准备合成提交清单</button><button onclick="run('approve')">确认执行本批合成操作</button><button onclick="run('repeat')">检查重复确认</button><button onclick="run('read')">读取当前页面</button><button onclick="run('next-page')">读取下一页</button><button onclick="run('find-upload')">搜索完整快照的上传入口</button><button onclick="run('receipt')">核对合成上传回执</button><button onclick="run('capture')">手动刷新画面</button><button onclick="run('records')">查看执行台账</button><a href="/workbench">打开完整工作台</a><p id="state">等待开始</p><pre id="result"></pre><img id="screen" hidden style="max-width:100%">
<script>async function run(action){document.querySelectorAll('button').forEach(b=>b.disabled=true);document.querySelector('#state').textContent='正在执行';try{let r=await fetch('/native/'+action,{method:'POST'});let d=await r.json();document.querySelector('#state').textContent=r.ok?'完成':'未完成';const {image,...metadata}=d;document.querySelector('#result').textContent=JSON.stringify(metadata,null,2);if(image){document.querySelector('#screen').src=image;document.querySelector('#screen').hidden=false;}}catch(e){document.querySelector('#state').textContent=String(e);}finally{document.querySelectorAll('button').forEach(b=>b.disabled=false);}}</script>'''

    def read():
        page = browser.call('read', cid, state['page']['session_id'])
        state['page'] = page
        return page

    @app.post('/native/open')
    def open_page():
        state['page'] = services.platform.execute(cid, 'browser_open', {'url': 'http://127.0.0.1:8087/' + ('large-form-host' if large_form_validation else 'preview-form' if preview_validation else 'tab-fixture' if tab_validation else 'continuation-fixture' if continuation else 'fixture')})
        return state['page']

    @app.post('/native/{action}')
    def action(action: str):
        if action in ('style', 'change'):
            if not preview_validation:
                raise ServiceError('未启用本机预览合成验收。', 403)
            key = 'style' if action == 'style' else 'value'
            state[key] += 1
            return preview_flags()
        if action == 'read':
            return read()
        if action in ('find-upload', 'next-page'):
            page = state['page']
            args = {'session_id': page['session_id'], 'snapshot_id': page['snapshot_id']}
            args.update({'query': '上传合成简历'} if action == 'find-upload' else {
                'text_offset': page.get('next_text_offset') or page['text_total'],
                'element_offset': page.get('next_element_offset') or page['element_total']})
            result = services.platform.execute(cid, 'browser_read', args)
            if action == 'next-page':
                state['page'] = result
            return result
        if action == 'receipt':
            return state.get('upload_receipt', {'not_uploaded': True})
        if action == 'records':
            return {'conversation_id': cid, 'records': services.tracking.store.records(agent.id)}
        if action == 'capture':
            return browser.call('capture', cid, state['page']['session_id'])
        if action == 'approve':
            return services.approvals.decide(state['pending']['id'], True)
        if action == 'repeat':
            try:
                services.approvals.decide(state['pending']['id'], True)
            except ServiceError as error:
                return {'duplicate_blocked': error.status_code == 409}
            return {'duplicate_blocked': False}
        page = read()
        def element(label):
            matches = [e for e in page['elements'] if e['label'] == label]
            if len(matches) != 1:
                raise ServiceError('合成控件不唯一：' + label, 409)
            return matches[0]['id']
        if action == 'tab-prepare':
            operations = [{'kind': 'click', 'element_id': element('打开空白标签（合成测试）')}]
        elif action == 'fill':
            operations = [{'kind': 'fill', 'element_id': element('姓名'), 'value': '合成候选人'},
                          {'kind': 'fill', 'element_id': element('技能'), 'value': 'Python / SQL；仅本地合成验收'}]
        elif action == 'upload':
            if large_form_validation:
                page = services.platform.execute(cid, 'browser_read', {'session_id': page['session_id'], 'snapshot_id': page['snapshot_id'], 'query': '上传合成简历'})
            operations = [{'kind': 'upload', 'element_id': element('拖拽或点击上传合成简历' if large_form_validation else '简历'), 'file_id': file['id']}]
        elif action == 'submit':
            operations = [{'kind': 'click', 'element_id': element('提交测试申请')}]
        else:
            raise ServiceError('未知验收操作。', 404)
        result = services.platform.execute(cid, 'browser_prepare_actions', {'session_id': page['session_id'],
            'snapshot_id': page['snapshot_id'], 'operations': operations})
        state['pending'] = result['pending_action']
        return result
    return app


if __name__ == '__main__':
    uvicorn.run(create_app(), host='127.0.0.1', port=8087)
