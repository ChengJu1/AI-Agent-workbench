# 提供 Agent 列表和单个 Agent 的统一查询入口。
# 其他后端模块通过这里访问 Agent Registry。
from app.models.api import AgentInfo
from app.services.agent_registry import AgentRegistry


registry = None


def get_registry():
    global registry
    if registry is None:
        registry = AgentRegistry()
    return registry


def list_agents():
    agent_list = []

    for agent in get_registry().list_agents():
        agent_info = AgentInfo(
            id=agent.id,
            name=agent.name,
            description=agent.description,
        )
        agent_list.append(agent_info)

    return agent_list


def get_agent(agent_id):
    return get_registry().get_agent(agent_id)
