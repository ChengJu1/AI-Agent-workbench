"""统一查询内置与用户 Agent；动态配置从数据库读取，保存后立即生效。"""
from uuid import uuid4

from app.models.agents import LoadedAgent, PermissionsManifest


class AgentCatalog:
    def __init__(self, builtins, store):
        self.builtins = builtins
        self.store = store

    def list_agents(self):
        return self.builtins.list_agents() + self.store.list_agents()

    def get_agent(self, agent_id):
        return self.builtins.get_agent(agent_id) or self.store.get(agent_id)

    def create(self, definition):
        agent = LoadedAgent(
            id=f"custom_{uuid4().hex}", name=definition.name,
            description=definition.description, system_prompt=definition.system_prompt,
            skills=[], tools=definition.tools, max_turns=definition.max_turns,
            permissions=PermissionsManifest(dry_run_by_default=True),
        )
        self.store.create(agent)
        return agent
