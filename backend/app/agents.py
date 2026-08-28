# 提供 Agent 列表和单个 Agent 的统一查询入口。
# 其他后端模块通过这里访问 Agent Registry。
from app.schemas import AgentInfo
from app.services.agent_registry import AgentRegistry


registry = AgentRegistry()


def list_agents():
    agent_list = []

    for agent in registry.list_agents(): # 提供一个更简单的agent查询方法
        agent_info = AgentInfo(
            id=agent.id,
            name=agent.name,
            description=agent.description,
        )
        agent_list.append(agent_info)

    return agent_list


def get_agent(agent_id):
    return registry.get_agent(agent_id)
