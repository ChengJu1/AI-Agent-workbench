"""负责人按需组队：可用工作区里的其他 Agent，也可创建临时 Agent；团队计划经用户确认后才能使用。"""
from app.errors import ServiceError
from app.models.agents import LoadedAgent, PermissionsManifest


MAX_PARTICIPANTS = 5
MAX_NAME_CHARS, MAX_INSTRUCTIONS_CHARS, MAX_SUMMARY_CHARS = 40, 2000, 2000


class TeamService:
    def __init__(self, registry, store):
        self.registry = registry
        self.store = store

    def candidates(self, lead):
        """负责人可以请来协助的现有 Agent：工作区里除自己以外未归档的 Agent。"""
        archived = self.registry.archived_ids()
        return [agent for agent in self.registry.list_agents() if agent.id != lead.id and agent.id not in archived]

    def temporary_agent(self, agent_id):
        row = self.store.temporary(agent_id)
        if row is None:
            return None
        return LoadedAgent(id=row['id'], name=row['name'], description='负责人按需创建的临时 Agent', system_prompt=row['instructions'],
                           skills=[], tools=[], platform_capabilities=row['capabilities'], permissions=PermissionsManifest(dry_run_by_default=True))

    def validate_plan(self, lead, plan):
        """检查并整理团队计划；临时 Agent 的能力只能是负责人能力的子集。"""
        if not isinstance(plan, dict):
            raise ServiceError('团队计划格式不正确。', 422)
        summary = str(plan.get('summary') or '').strip()
        participants = plan.get('participants')
        if not summary or len(summary) > MAX_SUMMARY_CHARS:
            raise ServiceError(f'计划说明需要 1–{MAX_SUMMARY_CHARS} 字。', 422)
        if not isinstance(participants, list) or not 1 <= len(participants) <= MAX_PARTICIPANTS:
            raise ServiceError(f'参与者需要 1–{MAX_PARTICIPANTS} 个。', 422)
        candidates = {agent.id: agent for agent in self.candidates(lead)}
        allowed = set(lead.platform_capabilities)
        normalized, seen = [], set()
        for item in participants:
            if not isinstance(item, dict):
                raise ServiceError('参与者格式不正确。', 422)
            role = str(item.get('role') or '').strip()[:200]
            if item.get('agent_id'):
                agent = candidates.get(item['agent_id'])
                if agent is None:
                    raise ServiceError(f"{item['agent_id']} 不是可用的 Agent（不存在、已归档或是负责人自己）。", 422)
                if agent.id in seen:
                    raise ServiceError(f'{agent.name} 重复出现在计划里。', 422)
                seen.add(agent.id)
                normalized.append({'agent_id': agent.id, 'name': agent.name, 'role': role})
                continue
            name = str(item.get('name') or '').strip()
            instructions = str(item.get('instructions') or '').strip()
            capabilities = item.get('capabilities') or []
            if not name or len(name) > MAX_NAME_CHARS or not instructions or len(instructions) > MAX_INSTRUCTIONS_CHARS:
                raise ServiceError(f'临时 Agent 需要名称（最多 {MAX_NAME_CHARS} 字）和职责说明（最多 {MAX_INSTRUCTIONS_CHARS} 字）。', 422)
            if not isinstance(capabilities, list) or not all(isinstance(value, str) for value in capabilities):
                raise ServiceError('临时 Agent 的能力格式不正确。', 422)
            extra = sorted(set(capabilities) - allowed)
            if extra:
                raise ServiceError(f"临时 Agent {name} 不能拥有负责人没有的能力：{'、'.join(extra)}。", 422)
            normalized.append({'name': name, 'instructions': instructions, 'capabilities': list(dict.fromkeys(capabilities)), 'role': role})
        return {'summary': summary, 'participants': normalized}

    def approve_plan(self, conversation_id, lead, proposed, edited=None):
        """用户批准计划：使用用户修改后的版本（若有），创建临时 Agent，返回交给负责人的结果。"""
        plan = self.validate_plan(lead, edited if edited is not None else proposed)
        participants = []
        for item in plan['participants']:
            if 'agent_id' in item:
                participants.append({**item, 'temporary': False})
            else:
                agent_id = self.store.create_temporary(conversation_id, lead.id, item['name'], item['instructions'], item['capabilities'])
                participants.append({**item, 'agent_id': agent_id, 'temporary': True})
        changed = edited is not None and self.validate_plan(lead, proposed) != plan
        lines = ['用户批准了团队计划' + ('（用户修改过，请按修改后的版本执行）' if changed else '') + '。可以使用的参与者：']
        lines += [f"- {item['agent_id']}：{item['name']}{'（临时）' if item['temporary'] else ''}" + (f"，分工：{item['role']}" if item['role'] else '')
                  for item in participants]
        return {'message': '\n'.join(lines), 'summary': plan['summary'], 'participants': participants, 'changed': changed}

    def approved_participants(self, conversation_id):
        """本会话最近一份已批准计划里的参与者 ID；有计划还在等待确认时返回 None。"""
        plans = self.store.plans(conversation_id)
        if any(plan['status'] in ('pending', 'executing') for plan in plans):
            return None
        approved = [plan for plan in plans if plan['status'] == 'approved' and plan['result']]
        return [item['agent_id'] for item in approved[-1]['result']['participants']] if approved else []

    def agent_name(self, agent_id):
        agent = self.registry.get_agent(agent_id)
        return agent.name if agent else '未知 Agent'

    def delegations(self, parent_id):
        return [{**row, 'member_name': self.agent_name(row['member_agent_id']), 'temporary': row['member_agent_id'].startswith('temp_')}
                for row in self.store.delegations(parent_id)]

    def parent(self, conversation_id):
        parent = self.store.parent(conversation_id)
        if parent is None:
            return None
        return {**parent, 'lead_agent_name': self.agent_name(parent['lead_agent_id'])}
