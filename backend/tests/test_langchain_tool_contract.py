"""Run explicitly in an isolated environment with LangChain Core installed; no models."""
import asyncio
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session

from app.application import create_app
from app.config import Settings
from app.container import build_services
from app.services.skill_loads import SkillLoads
from app.tools.platform_tools import platform_definitions
from app.tools.runtime_adapters import to_claude_sdk, to_langchain


class LangChainToolContracts(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.services = build_services(Settings(database_path=Path(temporary.name) / 'synthetic.db'))
        self.client = TestClient(create_app(services=self.services))
        self.addCleanup(self.client.close)
        self.skill = self.client.post('/api/skills', json={'name': '合成规则', 'description': '验证预算', 'content': '必须核对来源。'}).json()
        created = self.client.post('/api/agents', json={'name': '合成助手', 'description': '验证', 'system_prompt': '验证工具',
            'platform_capabilities': ['files'], 'skill_ids': [self.skill['id']]}).json()
        self.agent = self.services.registry.get_agent(created['id'])
        self.cid = self.services.store.create(self.agent.id)

    async def sdk_call(self, definitions, name, arguments):
        async with create_connected_server_and_client_session(to_claude_sdk('shared', definitions)['instance']) as session:
            result = await session.call_tool(name, arguments)
            return {'content': [item.model_dump(exclude_none=True) for item in result.content],
                    **({'is_error': True} if result.isError else {})}

    def test_platform_success_and_failure_have_identical_shared_handler_results(self):
        definitions, _ = platform_definitions(self.services.platform, self.cid, self.agent)
        tools = {tool.name: tool for tool in to_langchain(definitions, 'shared')}
        async def run():
            for name, arguments in [('list_files', {}), ('read_file', {'file_id': 'file_' + '0' * 32}),
                                    ('read_file', {'file_id': 'bad', 'unexpected': 1})]:
                expected = await self.sdk_call(definitions, name, arguments)
                actual = await tools[f'mcp__shared__{name}'].ainvoke(arguments)
                self.assertEqual(actual, expected)
        asyncio.run(run())
        self.assertEqual(len(self.services.tool_store.get_audit_logs(self.cid)), 4)

    def test_skill_budget_and_validation_are_identical(self):
        service = self.services.conversations.runtime._skill_tools
        async def run():
            sdk_loads, lc_loads = SkillLoads(10), SkillLoads(10)
            sdk_definitions = service.definitions(self.cid, self.agent, sdk_loads)
            tools = {tool.name: tool for tool in to_langchain(service.definitions(self.cid, self.agent, lc_loads))}
            for arguments in [{'skill_id': self.skill['id']}, {'skill_id': self.skill['id']}, {'skill_id': 'unknown'}, {}]:
                expected = await self.sdk_call(sdk_definitions, 'load_skill', arguments)
                actual = await tools['load_skill'].ainvoke(arguments)
                self.assertEqual(actual, expected)
            self.assertEqual(sdk_loads.snapshot(), lc_loads.snapshot())
        asyncio.run(run())

    def test_capability_revocation_is_checked_in_shared_layer_for_both_adapters(self):
        definitions, _ = platform_definitions(self.services.platform, self.cid, self.agent)
        tools = {tool.name: tool for tool in to_langchain(definitions)}
        response = self.client.put(f'/api/agents/{self.agent.id}/capabilities', json={'capabilities': []})
        self.assertEqual(response.status_code, 200)
        async def run():
            expected = await self.sdk_call(definitions, 'list_files', {})
            actual = await tools['list_files'].ainvoke({})
            self.assertTrue(actual['is_error'])
            self.assertEqual(actual, expected)
        asyncio.run(run())
