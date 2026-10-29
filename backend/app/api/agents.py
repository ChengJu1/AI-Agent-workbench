"""提供健康检查、Agent 简介和指定 Agent 的会话列表。"""
from fastapi import APIRouter, Depends

from app.api.dependencies import get_services
from app.errors import ServiceError
from app.models.api import AgentInfo, AgentKnowledgeRequest, ArchiveRequest, CreateAgentRequest
from app.models.knowledge import KnowledgeBaseInfo
from app.models.skills import AgentSkillsRequest, SkillInfo


router = APIRouter(prefix="/api")


@router.get("/health")
def health():
    return {"status": "ok"}


def agent_info(agent, services, archived=None):
    if archived is None:
        archived = agent.id in services.registry.archived_ids()
    return AgentInfo(id=agent.id, name=agent.name, description=agent.description,
                     platform_capabilities=agent.platform_capabilities, archived=archived,
                     deletable=not services.registry.is_builtin(agent.id))


@router.get("/agents", response_model=list[AgentInfo])
def list_agents(services=Depends(get_services)):
    archived = services.registry.archived_ids()
    return [agent_info(agent, services, agent.id in archived) for agent in services.registry.list_agents()]


@router.put("/agents/{agent_id}/archived", response_model=AgentInfo)
def archive_agent(agent_id: str, request: ArchiveRequest, services=Depends(get_services)):
    services.registry.set_archived(agent_id, request.archived)
    return agent_info(services.registry.get_agent(agent_id), services, request.archived)


@router.delete("/agents/{agent_id}")
def delete_agent(agent_id: str, services=Depends(get_services)):
    if services.registry.is_builtin(agent_id):
        raise ServiceError("内置 Agent 不能删除，可以归档。", 409)
    if services.registry.get_agent(agent_id) is None:
        raise ServiceError("Agent 不存在。", 404)
    deleted = services.conversations.delete_for_agent(agent_id)
    services.registry.delete(agent_id)
    return {"deleted": True, "conversations": deleted}


@router.post("/agents", response_model=AgentInfo, status_code=201)
def create_agent(request: CreateAgentRequest, services=Depends(get_services)):
    return agent_info(services.registry.create(request), services, False)


@router.get("/agents/{agent_id}/knowledge-bases", response_model=list[KnowledgeBaseInfo])
def get_agent_knowledge(agent_id: str, services=Depends(get_services)):
    agent = services.registry.get_agent(agent_id)
    if agent is None:
        raise ServiceError("Agent 不存在。", 404)
    ids = set(agent.knowledge_base_ids)
    return [base for base in services.knowledge.store.list_bases() if base["id"] in ids]


@router.put("/agents/{agent_id}/knowledge-bases", response_model=list[KnowledgeBaseInfo])
def bind_agent_knowledge(agent_id: str, request: AgentKnowledgeRequest, services=Depends(get_services)):
    services.registry.bind_knowledge(agent_id, request.knowledge_base_ids)
    return get_agent_knowledge(agent_id, services)


@router.get("/agents/{agent_id}/conversations")
def list_conversations(agent_id: str, services=Depends(get_services)):
    if services.registry.get_agent(agent_id) is None:
        raise ServiceError("Agent not found", 404)
    return services.store.list_conversations(agent_id)


@router.get("/agents/{agent_id}/skills", response_model=list[SkillInfo])
def get_agent_skills(agent_id: str, services=Depends(get_services)):
    agent = services.registry.get_agent(agent_id)
    if agent is None:
        raise ServiceError("Agent 不存在。", 404)
    return agent.bound_skills


@router.put("/agents/{agent_id}/skills", response_model=list[SkillInfo])
def bind_agent_skills(agent_id: str, request: AgentSkillsRequest, services=Depends(get_services)):
    services.registry.bind_skills(agent_id, request.skill_ids, request.skill_versions)
    return get_agent_skills(agent_id, services)

