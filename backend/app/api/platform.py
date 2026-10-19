from fastapi import APIRouter, Depends, UploadFile, File, Response
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
def read_file(conversation_id: str, file_id: str, services=Depends(get_services)):
    services.platform.require(conversation_id, 'files')
    return services.platform.files.read(conversation_id, file_id)


@router.get('/conversations/{conversation_id}/browser')
def browsers(conversation_id: str, services=Depends(get_services)):
    services.conversations.require_conversation(conversation_id)
    return services.platform.browser.call('list', conversation_id)


@router.get('/conversations/{conversation_id}/browser/{session_id}/screenshot')
def screenshot(conversation_id: str, session_id: str, services=Depends(get_services)):
    services.conversations.require_conversation(conversation_id)
    return Response(services.platform.browser.call('screenshot', conversation_id, session_id), media_type='image/png', headers={'Cache-Control': 'no-store'})


@router.post('/conversations/{conversation_id}/browser/{session_id}/takeover')
def takeover(conversation_id: str, session_id: str, request: Takeover, services=Depends(get_services)):
    services.platform.require(conversation_id, 'browser')
    return services.platform.browser.call('takeover', conversation_id, session_id, request.active)


@router.delete('/conversations/{conversation_id}/browser/{session_id}')
def close_browser(conversation_id: str, session_id: str, services=Depends(get_services)):
    services.conversations.require_conversation(conversation_id)
    return services.platform.browser.call('close', conversation_id, session_id)


@router.post('/conversations/{conversation_id}/browser', status_code=201)
def open_browser(conversation_id: str, request: OpenBrowser, services=Depends(get_services)):
    return services.platform.execute(conversation_id, 'browser_open', request.model_dump())
