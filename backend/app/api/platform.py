from fastapi import APIRouter, Depends, UploadFile, File, Response, Form, Query
from pydantic import BaseModel, ConfigDict, Field
from app.api.dependencies import get_services
from app.errors import ServiceError
from app.platform.catalog import Capability

router = APIRouter(prefix='/api')


class CapabilityBindings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    capabilities: list[Capability] = Field(default_factory=list)


class OpenBrowser(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: str = Field(min_length=1, max_length=3000)


class Takeover(BaseModel):
    model_config = ConfigDict(extra='forbid')
    active: bool
    duration_seconds: int = Field(default=60,ge=30,le=600,strict=True)


class InspectBrowser(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tab_index: int | None = Field(default=None, ge=0, le=99, strict=True)


@router.post('/conversations/{conversation_id}/browser/{session_id}/inspect')
def inspect_browser(conversation_id: str, session_id: str, request: InspectBrowser, services=Depends(get_services)):
    services.platform.require(conversation_id, 'browser')
    if services.platform.browser.status().get('provider') != 'native_mcp':
        raise ServiceError('当前浏览器方案不支持标签检查。', 422)
    result = services.platform.browser.call('read', conversation_id, session_id, request.tab_index)
    return {**{k: result[k] for k in ('url', 'title', 'page_state', 'authentication_state', 'tabs', 'diagnostics', 'notice') if k in result},
            'element_count': result.get('page_element_total', len(result.get('elements', []))),
            'text_length': result.get('page_text_total', len(result.get('text', '')))}


@router.get('/platform/capabilities')
def catalog(services=Depends(get_services)):
    return services.platform.catalog()


@router.get('/agents/{agent_id}/capabilities')
def bindings(agent_id: str, services=Depends(get_services)):
    agent = services.registry.get_agent(agent_id)
    if agent is None:
        raise ServiceError('Agent 不存在。', 404)
    return {'capabilities': agent.platform_capabilities}


@router.put('/agents/{agent_id}/capabilities')
def bind(agent_id: str, request: CapabilityBindings, services=Depends(get_services)):
    services.registry.bind_platform(agent_id, request.capabilities)
    return bindings(agent_id, services)


@router.get('/conversations/{conversation_id}/files')
def files(conversation_id: str, services=Depends(get_services)):
    services.conversations.require_conversation(conversation_id)
    return services.platform.files.list(conversation_id)


@router.post('/conversations/{conversation_id}/files', status_code=201)
async def upload(conversation_id: str, file: UploadFile = File(...), services=Depends(get_services)):
    services.platform.require(conversation_id, 'files')
    data = await file.read(2_000_001)
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(services.platform.files.upload, conversation_id, file.filename or '', data)


@router.get('/conversations/{conversation_id}/files/{file_id}')
def read_file(conversation_id: str, file_id: str, version: int | None = Query(default=None, ge=1), services=Depends(get_services)):
    services.platform.require(conversation_id, 'files')
    return services.platform.files.read(conversation_id, file_id, version=version)


@router.get('/conversations/{conversation_id}/browser')
def browsers(conversation_id: str, services=Depends(get_services)):
    services.conversations.require_conversation(conversation_id)
    return services.platform.browser.call('list', conversation_id)


@router.get('/conversations/{conversation_id}/browser/{session_id}/screenshot')
def screenshot(conversation_id: str, session_id: str, services=Depends(get_services)):
    services.conversations.require_conversation(conversation_id)
    return Response(services.platform.browser.call('screenshot', conversation_id, session_id), media_type='image/png', headers={'Cache-Control': 'no-store'})


def preview_plan(services, conversation_id, session_id, action_id):
    if not action_id:
        return None
    action = services.tool_store.get_pending_action(action_id)
    if not action or action['conversation_id'] != conversation_id or action['action'] != 'browser_actions' or action['params'].get('session_id') != session_id:
        raise ServiceError('操作清单不属于当前页面或会话。',404)
    return {**action['params'],'status':action['status']}


@router.get('/conversations/{conversation_id}/browser/{session_id}/preview')
def preview(conversation_id: str, session_id: str, response: Response, action_id: str | None = None, operation_index: int = Query(default=0,ge=0,le=11), services=Depends(get_services)):
    services.platform.require(conversation_id,'browser')
    response.headers['Cache-Control'] = 'no-store'
    plan = preview_plan(services,conversation_id,session_id,action_id)
    return services.platform.browser.call('preview',conversation_id,session_id,plan,operation_index)


class PreviewFocus(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action_id: str = Field(min_length=1,max_length=100)
    operation_index: int = Field(default=0,ge=0,le=11,strict=True)


class PreviewCapture(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action_id: str | None = Field(default=None, max_length=100)
    operation_index: int = Field(default=0, ge=0, le=11, strict=True)


@router.post('/conversations/{conversation_id}/browser/{session_id}/preview-capture')
def preview_capture(conversation_id: str, session_id: str, request: PreviewCapture,
                    response: Response, services=Depends(get_services)):
    services.platform.require(conversation_id, 'browser')
    response.headers['Cache-Control'] = 'no-store'
    plan = preview_plan(services, conversation_id, session_id, request.action_id)
    method = 'capture' if services.platform.browser.status().get('provider') == 'native_mcp' else 'preview'
    return services.platform.browser.call(method, conversation_id, session_id, plan, request.operation_index)


class ConnectionApproval(BaseModel):
    model_config=ConfigDict(extra='forbid')
    request_ids:list[str]=Field(min_length=1,max_length=64)
    page_url:str=Field(min_length=1,max_length=3000)
    allow_data:bool=Field(default=False,strict=True)


@router.get('/conversations/{conversation_id}/browser/{session_id}/connections')
def connection_list(conversation_id:str,session_id:str,response:Response,services=Depends(get_services)):
    services.platform.require(conversation_id,'browser')
    response.headers['Cache-Control']='no-store'
    return services.platform.browser.call('connection_list',conversation_id,session_id)


@router.post('/conversations/{conversation_id}/browser/{session_id}/connections')
def connection_allow(conversation_id:str,session_id:str,request:ConnectionApproval,services=Depends(get_services)):
    services.platform.require(conversation_id,'browser')
    result=services.platform.browser.call('connection_allow',conversation_id,session_id,request.request_ids,request.page_url,request.allow_data)
    services.tool_store.add_audit_log(conversation_id,services.store.get_agent_id(conversation_id),'workbench_platform',
        'authorize_browser_connections',{'session_id':session_id,'approved':result['approved']},'success',tool_type='browser')
    return result


@router.delete('/conversations/{conversation_id}/browser/{session_id}/connections')
def connection_revoke(conversation_id:str,session_id:str,services=Depends(get_services)):
    services.platform.require(conversation_id,'browser')
    result=services.platform.browser.call('connection_revoke',conversation_id,session_id)
    services.tool_store.add_audit_log(conversation_id,services.store.get_agent_id(conversation_id),'workbench_platform',
        'revoke_browser_connections',{'session_id':session_id},'success',tool_type='browser')
    return result


@router.post('/conversations/{conversation_id}/browser/{session_id}/preview-focus')
def preview_focus(conversation_id: str,session_id: str,request: PreviewFocus,response: Response,services=Depends(get_services)):
    services.platform.require(conversation_id,'browser')
    response.headers['Cache-Control'] = 'no-store'
    plan = preview_plan(services,conversation_id,session_id,request.action_id)
    return services.platform.browser.call('preview',conversation_id,session_id,plan,request.operation_index,True)


@router.post('/conversations/{conversation_id}/browser/{session_id}/takeover')
def takeover(conversation_id: str, session_id: str, request: Takeover, services=Depends(get_services)):
    services.platform.require(conversation_id, 'browser')
    return services.platform.browser.call('takeover', conversation_id, session_id, request.active,request.duration_seconds)


@router.post('/conversations/{conversation_id}/browser/{session_id}/reload')
def reload_browser(conversation_id: str,session_id: str,services=Depends(get_services)):
    services.platform.require(conversation_id,'browser')
    result = services.platform.browser.call('reload',conversation_id,session_id)
    return {key:result[key] for key in ('session_id','url','http_status','warning') if key in result}


@router.delete('/conversations/{conversation_id}/browser/{session_id}')
def close_browser(conversation_id: str, session_id: str, services=Depends(get_services)):
    services.conversations.require_conversation(conversation_id)
    return services.platform.browser.call('close', conversation_id, session_id)


@router.post('/conversations/{conversation_id}/browser', status_code=201)
def open_browser(conversation_id: str, request: OpenBrowser, services=Depends(get_services)):
    return services.platform.execute(conversation_id, 'browser_open', request.model_dump())


class LocalFile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str = Field(min_length=1, max_length=3000)
    file_id: str | None = None
    expected_version: int | None = Field(default=None, ge=1)


@router.post('/conversations/{conversation_id}/local-files', status_code=201)
def link_local(conversation_id: str, request: LocalFile, services=Depends(get_services)):
    services.platform.require(conversation_id, 'files')
    return services.platform.files.link_local(conversation_id, request.path, request.file_id, request.expected_version)


@router.put('/conversations/{conversation_id}/files/{file_id}')
async def update_file(conversation_id: str, file_id: str, expected_version: int = Form(ge=1), file: UploadFile = File(...), services=Depends(get_services)):
    services.platform.require(conversation_id, 'files')
    from starlette.concurrency import run_in_threadpool
    data = await file.read(2_000_001)
    return await run_in_threadpool(services.platform.files.update, conversation_id, file_id, expected_version, file.filename or '', data)


@router.get('/conversations/{conversation_id}/files/{file_id}/versions')
def versions(conversation_id: str, file_id: str, services=Depends(get_services)):
    services.platform.require(conversation_id, 'files')
    return services.platform.files.versions(conversation_id, file_id)


@router.get('/conversations/{conversation_id}/files/{file_id}/check')
def check_file(conversation_id: str, file_id: str, services=Depends(get_services)):
    services.platform.require(conversation_id, 'files')
    return services.platform.files.check(conversation_id, file_id)


class RefreshFile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=1, strict=True)


@router.post('/conversations/{conversation_id}/files/{file_id}/refresh')
def refresh_file(conversation_id: str, file_id: str, request: RefreshFile, services=Depends(get_services)):
    services.platform.require(conversation_id, 'files')
    plan = services.platform.files.prepare_update(conversation_id, file_id, request.expected_version)
    return services.platform.files.execute_update(conversation_id, plan)['file']
