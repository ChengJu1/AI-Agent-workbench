"""Builder lifecycle, actual test gate, version pinning and stdio MCP integration."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import ValidationError

from app.application import create_app
from app.capabilities.executor import PackageExecutor
from app.capabilities.sandbox import CodeSandbox, macos_profile
from app.config import Settings
from app.container import build_services
from app.errors import ServiceError
from app.models.builds import BuildPlan, StartBuild
from app.services.build_service import same_json


def plan_dict():
    return {'status': 'ready', 'message': '按输入数字计算总和，空数组返回零。',
            'name': '数字汇总', 'description': '汇总传入数字', 'system_prompt': '必须调用 sum_numbers 方法后回答。',
            'tools': [{'name': 'sum_numbers', 'description': '对输入数字求和',
                       'input_schema': {'type': 'object', 'properties': {'numbers': {'type': 'array', 'items': {'type': 'number'}}}, 'required': ['numbers'], 'additionalProperties': False},
                       'output_schema': {'type': 'object', 'properties': {'total': {'type': 'number'}}, 'required': ['total'], 'additionalProperties': False},
                       'code': 'def run(arguments):\n    return {"total": sum(arguments["numbers"])}',
                       'tests': [{'name': '正常输入', 'arguments': {'numbers': [1, 2, 3]}, 'expected': {'total': 6}},
                                 {'name': '空数组', 'arguments': {'numbers': []}, 'expected': {'total': 0}}]}]}


class FakeSandbox:
    def execute(self, code, arguments):
        return {'total': sum(arguments['numbers'])}

    def status(self):
        return {'available': True, 'message': 'test'}


class BuilderTestCase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.settings = Settings(database_path=Path(temporary.name) / 'builder.db')
        self.services = build_services(self.settings)
        self.service = self.services.agent_builds
        self.service.generator = AsyncMock()
        self.service.generator.generate.return_value = BuildPlan.model_validate(plan_dict())
        self.service.sandbox = FakeSandbox()
        self.client = TestClient(create_app(services=self.services))
        self.addCleanup(self.client.close)

    def start(self, **extra):
        request = {'request_id': str(uuid4()), 'message': '创建数字求和方法，空数组返回零', **extra}
        response = self.client.post('/api/agent-builds', json=request)
        self.assertEqual(response.status_code, 202, response.text)
        return self.service.store.get(request['request_id'])

    def publish(self, build):
        response = self.client.post(f"/api/agent-builds/{build['id']}/publish", json={'expected_revision': build['revision']})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_generate_test_publish_and_runtime_wiring(self):
        build = self.start()
        self.assertEqual(build['status'], 'ready')
        self.assertTrue(all(test['passed'] for test in build['tests']))
        info = self.publish(build)
        self.assertIn(info, self.client.get('/api/agents').json())
        agent = self.services.registry.get_agent(info['id'])
        ref = agent.generated_tools[0]
        self.assertEqual(ref.version, 1)
        options, audit, _ = self.services.conversations.runtime._build_options('test', agent, False, '')
        name = f'generated_{ref.package_id}'
        self.assertEqual(options.mcp_servers[name]['command'], sys.executable)
        self.assertIn(str(self.settings.database_path.resolve()), options.mcp_servers[name]['args'])
        self.assertEqual(audit, [f'mcp__{name}__sum_numbers'])
        self.assertEqual(self.publish(build), info)  # Idempotent publication.
        fresh = build_services(self.settings)
        self.assertEqual(fresh.registry.get_agent(info['id']).generated_tools, agent.generated_tools)
        summaries = self.client.get('/api/agent-builds').json()
        self.assertNotIn('plan', summaries[0])

    def test_failed_actual_tests_cannot_publish_and_feedback_is_sent(self):
        bad = plan_dict()
        bad['tools'][0]['tests'][0]['expected']['total'] = 999
        self.service.generator.generate.return_value = BuildPlan.model_validate(bad)
        build = self.start()
        self.assertEqual(build['status'], 'failed')
        self.assertEqual(self.service.generator.generate.await_count, 2)
        self.assertFalse(build['tests'][0]['passed'])
        response = self.client.post(f"/api/agent-builds/{build['id']}/publish", json={'expected_revision': build['revision']})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.service.store.packages(), [])

    def test_clarification_then_revision_and_stale_request(self):
        self.service.generator.generate.return_value = BuildPlan(status='needs_input', message='如何处理空数组？')
        build = self.start()
        self.assertEqual(build['status'], 'needs_input')
        self.service.generator.generate.return_value = BuildPlan.model_validate(plan_dict())
        path = f"/api/agent-builds/{build['id']}/messages"
        response = self.client.post(path, json={'message': '空数组返回零', 'expected_revision': 1})
        self.assertEqual(response.status_code, 202)
        updated = self.service.store.get(build['id'])
        self.assertEqual(updated['status'], 'ready')
        self.assertEqual(updated['revision'], 2)
        self.assertEqual(self.client.post(path, json={'message': '修改', 'expected_revision': 1}).status_code, 409)

    def test_versions_remain_pinned_and_conflicting_branch_is_rejected(self):
        build1 = self.start()
        agent1 = self.services.registry.get_agent(self.publish(build1)['id'])
        package_id = agent1.generated_tools[0].package_id
        build2 = self.start(base_package_id=package_id)
        competing = self.start(base_package_id=package_id)
        agent2 = self.services.registry.get_agent(self.publish(build2)['id'])
        self.assertEqual(agent2.generated_tools[0].version, 2)
        self.assertEqual(self.services.registry.get_agent(agent1.id).generated_tools[0].version, 1)
        self.assertEqual(self.client.post(f"/api/agent-builds/{competing['id']}/publish", json={'expected_revision': competing['revision']}).status_code, 409)

    def test_publication_rolls_back_package_if_agent_save_fails(self):
        build = self.start()
        with patch('app.storage.build_store.AgentStore.create_in_connection', side_effect=ServiceError('test', 409)):
            response = self.client.post(f"/api/agent-builds/{build['id']}/publish", json={'expected_revision': 1})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.service.store.packages(), [])
        self.assertEqual(self.service.store.get(build['id'])['status'], 'ready')
        self.publish(build)

    def test_hash_and_agent_binding_are_rechecked(self):
        build = self.start()
        agent = self.services.registry.get_agent(self.publish(build)['id'])
        ref = agent.generated_tools[0]
        executor = PackageExecutor(self.service.store.database, ref.package_id, 1, agent.id, FakeSandbox())
        self.assertEqual(executor.execute('sum_numbers', {'numbers': [7, 8]}), {'total': 15})
        for arguments in ({'numbers': 'bad'}, {'numbers': [], 'extra': 'bad'}):
            with self.assertRaises(ServiceError):
                executor.execute('sum_numbers', arguments)
        with self.assertRaises(ServiceError):
            PackageExecutor(self.service.store.database, ref.package_id, 1, 'missing')
        with self.service.store.database.connection() as connection:
            row = connection.execute('SELECT definition FROM capability_packages').fetchone()
            package = json.loads(row['definition']);package['plan']['tools'][0]['code'] = 'def run(arguments):\n    return {}'
            connection.execute('UPDATE capability_packages SET definition=?', (json.dumps(package),))
        with self.assertRaises(ServiceError):
            executor.execute('sum_numbers', {'numbers': []})

    def test_idempotent_start_and_interrupted_job_recovery(self):
        request = StartBuild(request_id=uuid4(), message='创建数字汇总')
        build, created = self.service.store.start(request)
        self.assertTrue(created)
        self.assertFalse(self.service.store.start(request)[1])
        with self.assertRaises(ServiceError):
            self.service.store.start(request.model_copy(update={'message': '其他需求'}))
        self.service.store.update(build['id'], 1, started_at=0)
        interrupted = self.service.store.get(build['id'])
        self.assertEqual(interrupted['status'], 'failed')
        self.assertIsNone(self.service.store.update(build['id'], 1, status='ready'))

    def test_schema_and_code_escape_attempts_are_rejected(self):
        for code in ['import os\ndef run(arguments):\n    return {}', 'def run(arguments):\n    return arguments.__class__', 'def run(arguments):\n    return __import__("os")']:
            data = plan_dict();data['tools'][0]['code'] = code
            with self.assertRaises(ValidationError):
                BuildPlan.model_validate(data)
        data = plan_dict();data['tools'][0]['input_schema']['$ref'] = 'https://example.com/schema'
        with self.assertRaises(ValidationError):
            BuildPlan.model_validate(data)

    def test_numeric_representation_is_not_a_false_test_failure(self):
        self.assertTrue(same_json({'total': 6.0}, {'total': 6}))
        self.assertFalse(same_json({'value': True}, {'value': 1}))
        self.assertFalse(same_json({'values': [1, 2]}, {'values': [2, 1]}))


@unittest.skipUnless(os.getenv('WORKBENCH_RUN_SANDBOX_TESTS') == '1', 'Run explicitly on host to verify OS isolation, not inside nested tool sandbox')
class HostSandboxIntegrationTest(unittest.TestCase):
    setUp = BuilderTestCase.setUp
    start = BuilderTestCase.start
    publish = BuilderTestCase.publish

    def test_actual_code_through_independent_stdio_mcp(self):
        self.service.sandbox = CodeSandbox()
        build = self.start()
        self.assertEqual(build['status'], 'ready', build['error'])
        agent = self.services.registry.get_agent(self.publish(build)['id'])
        ref = agent.generated_tools[0]

        async def check():
            params = StdioServerParameters(command=sys.executable, args=['-m', 'app.generated_mcp_server', '--database', str(self.settings.database_path), '--package', ref.package_id, '--version', '1', '--agent', agent.id], cwd=str(Path(__file__).resolve().parents[1]))
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self.assertEqual([tool.name for tool in (await session.list_tools()).tools], ['sum_numbers'])
                    result = await session.call_tool('sum_numbers', {'numbers': [11, 22]})
                    self.assertFalse(result.isError, result)
                    self.assertEqual(result.structuredContent, {'total': 33})
                    rejected = await session.call_tool('sum_numbers', {'numbers': 'bad'})
                    self.assertTrue(rejected.isError)
        asyncio.run(check())

    @unittest.skipUnless(sys.platform == 'darwin', 'macOS policy probe')
    def test_os_policy_blocks_file_write_read_and_network(self):
        with tempfile.TemporaryDirectory() as temp:
            secret = Path(temp) / 'private.txt';secret.write_text('synthetic-private-data')
            target = Path(temp) / 'must-not-exist.txt'
            probes = [f'open({str(secret)!r}).read()', f'open({str(target)!r},"w").write("x")', 'import socket; socket.socket().connect(("127.0.0.1", 9))']
            for code in probes:
                result = subprocess.run(['/usr/bin/sandbox-exec', '-p', macos_profile(), sys.executable, '-I', '-S', '-c', code], capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('PermissionError', result.stderr)
                self.assertNotIn('synthetic-private-data', result.stdout)
            self.assertFalse(target.exists())

    def test_infinite_loop_is_killed_and_credentials_are_not_inherited(self):
        sandbox = CodeSandbox()
        with self.assertRaises(ServiceError):
            sandbox.execute('def run(arguments):\n    while True:\n        pass', {})
        import app.capabilities.sandbox as module
        real = module.subprocess.Popen
        observed = []
        def capture(*args, **kwargs):
            observed.append(kwargs['env'])
            return real(*args, **kwargs)
        with patch.object(module.subprocess, 'Popen', side_effect=capture), patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'synthetic-secret'}):
            self.assertEqual(sandbox.execute('def run(arguments):\n    return {}', {}), {})
        self.assertNotIn('ANTHROPIC_API_KEY', observed[0])
