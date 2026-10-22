"""Creation-time discovery, provenance, fixed bindings and reviewed draft persistence."""
import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import test_agent_builder as fixtures
from test_agent_builder import plan_dict
from app.models.builds import BuildPlan
from app.models.skills import SkillDefinition
from app.services.build_skills import BuildSkillDiscovery, SERVER_NAME
from app.services.build_generator import BuildGenerator
from app.errors import ServiceError
from app.runtime.prompts import build_system_prompt
from app.services.skill_loads import SkillLoads
from scripted_turn import ScriptedTurn


class BuildSkillTests(unittest.TestCase):
    setUp = fixtures.BuilderTestCase.setUp
    start = fixtures.BuilderTestCase.start
    publish = fixtures.BuilderTestCase.publish

    def skill(self, name='周报整理', content='## 工作方法\n先提取成果、阻碍、下周计划；未提供的事实标记未知。'):
        return self.services.skills.save(SkillDefinition(name=name, description='将项目记录整理为周报，保留事实出处。', content=content))

    def reuse_plan(self, skill):
        return BuildPlan(status='ready', message='复用周报规则；工具按任务单独配置。', name='周报助手', description='整理用户提供的工作记录',
                         system_prompt='相关任务按需读取已绑定 Skill，缺少依据标记未知。',
                         reused_skills=[{'skill_id': skill['id'], 'version': skill['version'], 'reason': '覆盖成果和阻碍整理，工时统计仍需额外方法。', 'coverage': 'partial'}])

    def use_discovery(self, plan):
        async def generate(history, previous, feedback, discovery):
            discovery.initial(previous)
            discovery.search({'query': '周报'})
            for ref in plan.reused_skills:
                discovery.read({'skill_id': ref.skill_id, 'version': ref.version})
            return plan
        self.service.generator.generate.side_effect = generate

    def test_metadata_only_bounded_paging_and_no_match(self):
        for index in range(25):
            self.skill(f'周报规则 {index}', content='PRIVATE_BODY_NEVER_IN_CATALOG')
        discovery = BuildSkillDiscovery(self.service.store.database)
        first = discovery.initial()['catalog']
        self.assertEqual(first['total_skills'], 25)
        self.assertEqual(len(first['matches']), 8)
        self.assertEqual(first['next_offset'], 8)
        self.assertNotIn('PRIVATE_BODY', json.dumps(first))
        second = discovery.search({'query': '周报', 'offset': 8, 'limit': 20})
        self.assertEqual(len(second['matches']), 17)
        self.assertIsNone(second['next_offset'])
        self.assertFalse(discovery.snapshot()['read_skills'])
        self.assertFalse(discovery.search({'query': '完全不相关'})['matches'])

    def test_read_requires_discovered_version_and_enforces_budget(self):
        skill = self.skill(content='123456')
        discovery = BuildSkillDiscovery(self.service.store.database, budget_chars=8)
        args = {'skill_id': skill['id'], 'version': 1}
        with self.assertRaises(ServiceError):
            discovery.read(args)
        discovery.initial()
        self.assertEqual(discovery.read(args)['content'], '123456')
        with self.assertRaises(ServiceError):
            discovery.read(args)
        self.assertEqual(len(discovery.snapshot()['read_skills']), 1)
        with self.assertRaises(ServiceError):
            discovery.read({**args, 'version': 2})

    def test_unread_reuse_is_rejected_and_sent_back_for_repair(self):
        skill = self.skill()
        self.service.generator.generate.return_value = self.reuse_plan(skill)
        build = self.start()
        self.assertEqual(build['status'], 'failed')
        self.assertEqual(self.service.generator.generate.await_count, 2)
        self.assertIn('尚未实际读取', self.service.generator.generate.await_args_list[1].args[2])
        self.assertFalse(build['skill_review']['read_skills'])
        self.assertEqual(self.service.store.packages(), [])

    def test_skill_only_agent_pins_read_version_and_uses_runtime_reader(self):
        skill = self.skill()
        plan = self.reuse_plan(skill)
        plan.reused_skills[0].name = '伪造名称'
        self.use_discovery(plan)
        build = self.start()
        self.assertEqual(build['status'], 'ready', build['error'])
        self.assertEqual(build['plan']['reused_skills'][0]['name'], skill['name'])
        self.assertEqual(len(build['skill_review']['read_skills']), 1)
        self.services.skills.save(SkillDefinition(name=skill['name'], description=skill['description'], content='这是 v2'), skill['id'], 1)
        info = self.publish(build)
        agent = self.services.registry.get_agent(info['id'])
        self.assertEqual(agent.bound_skills[0].version, 1)
        self.assertEqual(agent.bound_skills[0].content, skill['content'])
        turn = self.services.deep_agents.tool_services.prepare('test', agent, None, SkillLoads(1000))
        self.assertIn('load_skill', {definition.name for definition in turn.groups['workbench_skills']})
        prompt = build_system_prompt(agent, '', 1000)
        self.assertNotIn(skill['content'], prompt)
        self.assertIn(plan.reused_skills[0].reason, prompt)
        self.assertEqual(self.client.get(f"/api/skills/{skill['id']}?version=1").json()['content'], skill['content'])
        second = self.start(base_package_id=agent.generated_tools[0].package_id)
        self.assertEqual(second['status'], 'ready', second['error'])
        self.assertEqual(second['plan']['reused_skills'][0]['version'], 1)

    def test_draft_save_is_reviewed_editable_atomic_and_pinned(self):
        draft = {'name': '新方法草稿', 'description': '适用场景', 'content': '## 步骤\n核对依据。', 'reason': '补齐方法缺口。'}
        self.service.generator.generate.return_value = BuildPlan(status='ready', message='建议保存新方法。', name='新助手', description='处理文本', system_prompt='按需读取工作方法。', skill_drafts=[draft])
        build = self.start()
        self.assertEqual(build['status'], 'ready')
        self.assertEqual(self.services.skills.list(), [])
        self.assertEqual(self.client.post(f"/api/agent-builds/{build['id']}/publish", json={'expected_revision': 1}).status_code, 422)
        path = f"/api/agent-builds/{build['id']}/skill-drafts/0"
        request = {'expected_revision': 1, 'action': 'save', 'definition': {k: draft[k] for k in ('name', 'description', 'content')}}
        request['definition']['content'] = '## 用户修改\n保留事实出处。'
        response = self.client.post(path, json=request)
        self.assertEqual(response.status_code, 200, response.text)
        updated = response.json()
        self.assertEqual(updated['revision'], 2)
        self.assertFalse(updated['plan']['skill_drafts'])
        self.assertEqual(len(self.services.skills.list()), 1)
        self.assertEqual(self.client.post(path, json=request).status_code, 409)
        agent = self.services.registry.get_agent(self.publish(updated)['id'])
        self.assertEqual(agent.bound_skills[0].content, request['definition']['content'])

    def test_duplicate_name_and_discard_are_transactional(self):
        skill = self.skill()
        plan = plan_dict()
        plan['skill_drafts'] = [{'name': skill['name'], 'description': 'test', 'content': 'test', 'reason': 'test'}]
        self.service.generator.generate.return_value = BuildPlan.model_validate(plan)
        build = self.start()
        path = f"/api/agent-builds/{build['id']}/skill-drafts/0"
        definition = {key: plan['skill_drafts'][0][key] for key in ('name', 'description', 'content')}
        self.assertEqual(self.client.post(path, json={'expected_revision': 1, 'action': 'save', 'definition': definition}).status_code, 409)
        self.assertEqual(len(self.services.skills.list()), 1)
        self.assertEqual(self.service.store.get(build['id'])['revision'], 1)
        response = self.client.post(path, json={'expected_revision': 1, 'action': 'discard'})
        self.assertEqual(response.status_code, 200)
        self.publish(response.json())

    def test_builder_only_has_readonly_skill_tools_without_body_preload(self):
        skill = self.skill(content='SYNTHETIC_SECRET_RULE_BODY')
        discovery = BuildSkillDiscovery(self.service.store.database)
        data = plan_dict()
        bound = []

        class BuilderModel(ScriptedTurn):
            def bind_tools(self, tools, **kwargs):
                bound.extend(tool.name for tool in tools)
                return self

        model = BuilderModel(responses=['unused'], reply=json.dumps(data),
                             calls=[(f'mcp__{SERVER_NAME}__search_skills', {'query': '周报'})])
        plan = asyncio.run(BuildGenerator(lambda: model).generate([{'role': 'user', 'content': '生成计算方法'}], discovery=discovery))
        self.assertEqual(plan.name, data['name'])
        self.assertNotIn(skill['content'], str(model.seen[0]))  # Bodies are read through read_skill, never preloaded.
        self.assertEqual(set(bound), {f'mcp__{SERVER_NAME}__search_skills', f'mcp__{SERVER_NAME}__read_skill'})
        self.assertNotIn(skill['content'], json.dumps(model.results, ensure_ascii=False))  # Search returns metadata only.

    def test_builder_reports_missing_model_and_model_failure_safely(self):
        with self.assertRaises(ServiceError) as missing:
            asyncio.run(BuildGenerator().generate([{'role': 'user', 'content': '生成'}]))
        self.assertEqual(missing.exception.status_code, 503)
        failing = ScriptedTurn(responses=['unused'], fail_after_tools=True)
        with patch('app.services.build_generator.logger.exception'), self.assertRaises(ServiceError) as failed:
            asyncio.run(BuildGenerator(lambda: failing).generate([{'role': 'user', 'content': '生成'}]))
        self.assertEqual(failed.exception.status_code, 502)
        self.assertNotIn('private-model-details', str(failed.exception))
