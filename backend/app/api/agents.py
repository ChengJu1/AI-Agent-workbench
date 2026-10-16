"""提供健康检查、Agent 简介和指定 Agent 的会话列表。"""
from fastapi import APIRouter, Depends

from app.api.dependencies import get_services
from app.errors import ServiceError
from app.models.api import AgentInfo, CreateAgentRequest


router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/agents", response_model=list[AgentInfo])
def list_agents(services=Depends(get_services)):
    agents = []
    for agent in services.registry.list_agents():
        agents.append(AgentInfo(id=agent.id, name=agent.name, description=agent.description))
    return agents


@router.post("/agents", response_model=AgentInfo, status_code=201)
def create_agent(request: CreateAgentRequest, services=Depends(get_services)):
    agent = services.registry.create(request)
    return AgentInfo(id=agent.id, name=agent.name, description=agent.description)


@router.get("/agents/{agent_id}/conversations")
def list_conversations(agent_id: str, services=Depends(get_services)):
    if services.registry.get_agent(agent_id) is None:
        raise ServiceError("Agent not found", 404)
    return services.store.list_conversations(agent_id)
