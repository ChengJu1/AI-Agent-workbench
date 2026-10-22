"""Local UI acceptance only: synthetic actions, fake execution, no browser/model."""
from pathlib import Path
import sys,time
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.responses import HTMLResponse,FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from app.application import create_app
from app.config import Settings
from app.container import Services
from app.errors import ServiceError
from app.models.api import CreateAgentRequest
from app.services.agent_registry import AgentRegistry
from app.storage.database import Database
from app.storage.conversation_store import ConversationStore
from app.storage.tool_store import ToolStore
from app.tools.cli_adapter import CliAdapter


def create_validation_app():
    root=Path(__file__).resolve().parents[1]/'data/platform-validation'
    database=Database(root/f'approval-ui-{uuid4().hex}.db');database.initialize()
    counts={'attempts':{},'executions':{},'continuations':0}
    class Runtime:
        async def stream_reply(self,*args,**kwargs):
            counts['continuations']+=1
            yield {'type':'delta','content':'合成操作结果已核对。本验收没有连接或操控任何招聘网站。'}
    services=Services(AgentRegistry(),ConversationStore(database),ToolStore(database),CliAdapter(),Runtime())
    class NoBrowser:
        def status(self):return {'available':False,'provider':'ui_fixture','message':'合成验收未连接浏览器'}
        def call(self,method,*args):
            if method=='list':return []
            raise ServiceError('UI 验收不允许操控网页。',403)
        def close(self):pass
    services.platform.browser=NoBrowser()
    agent=services.registry.create(CreateAgentRequest(name='确认交互验收',description='本机合成清单，不连接真实网站',system_prompt='仅供合成交互验收。',platform_capabilities=['browser']))
    cid=services.store.create(agent.id)
    services.store.add_message(cid,'user','验证确认弹框、状态同步和重复点击。全部为本机合成资料，不操控招聘网站。')
    ids={}
    def add(key,label,count=1,expired=False):
        params={'scenario':key,'session_id':'browser_'+'1'*32,'url':'https://example.com/synthetic','title':'本机合成页面',
                'expires_at':time.time()+(-60 if expired else 3600),
                'operations':[{'kind':'fill','label':label+(f' · 字段 {i+1}' if count>1 else ''),
                               'value':('这是一段用于验证滚动的合成资料，不属于真实简历。'*20 if count>1 else '仅为合成资料'),
                               'destination':'本机模拟执行，不发送网络请求'} for i in range(count)]}
        ids[key]=services.tool_store.create_pending_action(cid,agent.id,'workbench_platform','browser_actions',params)
    add('long','长清单滚动验收',24)
    add('failure','执行失败反馈验收')
    add('slow','快速连点验收')
    add('expired','过期清单验收',expired=True)
    add('external','另一窗口状态同步验收')
    def execute(action):
        key=action['params']['scenario'];counts['attempts'][key]=counts['attempts'].get(key,0)+1
        if key=='failure':raise ServiceError('合成操作失败：页面已变化，本次没有执行。',409)
        if key=='slow':time.sleep(2)
        counts['executions'][key]=counts['executions'].get(key,0)+1
        return {'message':'已完成本机合成操作，未操控真实网站。'}
    services.platform.execute_approved=execute
    app=create_app(Settings(database_path=database.path),services)
    dist=root/'approval-ui-dist'
    app.mount('/assets',StaticFiles(directory=dist/'assets'),name='approval-assets')
    @app.get('/workbench')
    def workbench():return FileResponse(dist/'index.html')
    @app.get('/',response_class=HTMLResponse)
    def home():
        return '''<!doctype html><meta charset="utf-8"><title>确认交互验收控制台</title><h1>本机合成 UI 验收</h1><a href="/workbench">打开完整工作台</a><p>没有真实浏览器、没有模型调用、没有外部提交。</p><button onclick="run('external')">模拟另一窗口取消操作</button><button onclick="run('counts')">查看执行次数</button><pre id="result"></pre><script>async function run(action){const r=await fetch('/fixture/'+action,{method:'POST'});document.querySelector('#result').textContent=JSON.stringify(await r.json(),null,2)}</script>'''
    @app.post('/fixture/{action}')
    def fixture(action:str):
        if action=='external':
            row=services.tool_store.get_pending_action(ids['external'])
            services.tool_store.finish_action(row,'cancelled','另一窗口取消了本机合成操作。',expected_status='pending')
        return counts
    return app

if __name__=='__main__':uvicorn.run(create_validation_app(),host='127.0.0.1',port=8087)
