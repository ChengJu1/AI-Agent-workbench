"""管理 Agent 团队：负责人可以把任务委派给成员，成员在各自的子会话里运行。"""
from app.errors import ServiceError


MAX_TEAM_MEMBERS = 5


class TeamService:
    def __init__(self, registry, store):
        self.registry = registry
        self.store = store

    def _require_agent(self, agent_id):
        agent = self.registry.get_agent(agent_id)
        if agent is None:
            raise ServiceError('Agent 不存在。', 404)
        return agent

    def members(self, lead_id):
        self._require_agent(lead_id)
        # 成员 Agent 被删除时团队关系会一起删除，这里再过滤一次以防万一。
        return [agent for agent in map(self.registry.get_agent, self.store.members(lead_id)) if agent is not None]

    def mode(self, lead_id):
        return self.store.mode(lead_id)

    def set_members(self, lead_id, member_ids, mode=None):
        self._require_agent(lead_id)
        member_ids = list(dict.fromkeys(member_ids))
        if len(member_ids) > MAX_TEAM_MEMBERS:
            raise ServiceError(f'团队成员最多 {MAX_TEAM_MEMBERS} 个。', 422)
        if lead_id in member_ids:
            raise ServiceError('Agent 不能把自己加为团队成员。', 422)
        archived = self.registry.archived_ids()
        for member_id in member_ids:
            member = self._require_agent(member_id)
            if member_id in archived:
                raise ServiceError(f'{member.name} 已归档，恢复后才能加入团队。', 409)
        self.store.set_members(lead_id, member_ids)
        if mode is not None:
            self.store.set_mode(lead_id, mode)
        return self.members(lead_id)

    def delegations(self, parent_id):
        names = {agent.id: agent.name for agent in self.registry.list_agents()}
        return [{**row, 'member_name': names.get(row['member_agent_id'], '未知 Agent')} for row in self.store.delegations(parent_id)]

    def parent(self, conversation_id):
        parent = self.store.parent(conversation_id)
        if parent is None:
            return None
        lead = self.registry.get_agent(parent['lead_agent_id'])
        return {**parent, 'lead_agent_name': lead.name if lead else '未知 Agent'}
