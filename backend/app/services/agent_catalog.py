"""统一查询内置与用户 Agent；动态配置从数据库读取，保存后立即生效。"""
from uuid import uuid4

from app.models.agents import LoadedAgent, PermissionsManifest
from app.errors import ServiceError
from app.models.skills import SkillInfo


class AgentCatalog:
    def __init__(self, builtins, store, skills):
        self.builtins = builtins
        self.store = store
        self.skills = skills

    def list_agents(self):
        return self.builtins.list_agents() + self.store.list_agents()

    def get_agent(self, agent_id):
        builtin = self.builtins.get_agent(agent_id)
        if builtin:
            agent = builtin.model_copy(update={"knowledge_base_ids": self.store.get_knowledge_base_ids(agent_id)})
        else:
            agent = self.store.get(agent_id)
        if agent is None:
            return None
        return agent.model_copy(update={"bound_skills": [SkillInfo.model_validate(skill) for skill in self.skills.get_for_agent(agent_id)]})

    def bind_skills(self, agent_id, skill_ids, skill_versions=None):
        agent = self.builtins.get_agent(agent_id) or self.store.get(agent_id)
        if agent is None:
            raise ServiceError("Agent 不存在。", 404)
        if skill_ids and any(tool.name == "workbench_skills" for tool in agent.tools):
            raise ServiceError("该 Agent 的 MCP 连接名称与 Skill 工具冲突，请使用其他连接名称。", 409)
        self.skills.bind(agent_id, skill_ids, skill_versions)

    def bind_knowledge(self, agent_id, base_ids):
        agent = self.get_agent(agent_id)
        if agent is None:
            raise ServiceError("Agent 不存在。", 404)
        if base_ids and any(tool.name == "workbench_knowledge" for tool in agent.tools):
            raise ServiceError("该 Agent 的 MCP 连接名称与知识库工具冲突，请使用其他连接名称。", 409)
        self.store.set_knowledge_base_ids(agent_id, base_ids)

    def create(self, definition):
        agent = LoadedAgent(
            id=f"custom_{uuid4().hex}", name=definition.name,
            description=definition.description, system_prompt=definition.system_prompt,
            skills=[], tools=definition.tools, max_turns=definition.max_turns,
            knowledge_base_ids=definition.knowledge_base_ids,
            bound_skills=[SkillInfo.model_validate(self.skills.get(skill_id, definition.skill_versions.get(skill_id)))
                          for skill_id in definition.skill_ids],
            permissions=PermissionsManifest(dry_run_by_default=True),
        )
        self.store.create(agent)
        return agent
