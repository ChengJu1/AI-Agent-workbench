"""Exercise tool-boundary audits, scoped MCP sessions and cancellation without a model."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import sys
import tempfile
import unittest

from mcp.types import CallToolResult, ListToolsResult, Tool

from app.services.knowledge_evidence import KnowledgeEvidence
from app.services.mcp_audit import McpAuditTracker
from app.services.notes_evidence import NotesEvidenceTracker
from app.storage.conversation_store import ConversationStore
from app.storage.database import Database
from app.storage.tool_store import ToolStore
from app.tools.external_tools import ExternalToolServer, open_mcp_session


class ExternalToolTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        database = Database(Path(temporary.name) / 'synthetic.db')
        database.initialize()
        self.store = ToolStore(database)
        self.cid = ConversationStore(database).create('fake')
        self.evidence = KnowledgeEvidence()
        self.audit = McpAuditTracker(self.store, self.cid, 'fake',
            [f'mcp__notes__{name}' for name in ('search_notes', 'read_note', 'slow')],
            NotesEvidenceTracker(self.evidence, {'notes'}).capture)
        self.opens, self.closes, self.calls = 0, 0, []
        self.started = None

    @asynccontextmanager
    async def opener(self, config):
        self.opens += 1
        owner = self
        class Session:
            async def list_tools(self, cursor=None):
                return ListToolsResult(tools=[Tool(name=name, description=name,
                    inputSchema={'type': 'object', 'properties': {'query': {'type': 'string'}},
                                 'required': ['query'], 'additionalProperties': False})
                    for name in ('search_notes', 'read_note', 'slow', 'forbidden')])

            async def call_tool(self, name, arguments):
                owner.calls.append((name, arguments))
                if name == 'slow':
                    owner.started.set()
                    await asyncio.Event().wait()
                if name == 'read_note':
                    raise RuntimeError('private-provider-token')
                return CallToolResult(content=[{'type': 'text', 'text': '{"schema":"bad"}'}])
        try:
            yield Session()
        finally:
            self.closes += 1

    def server(self):
        return ExternalToolServer('notes', {'type': 'http', 'url': 'unused'},
                                  ['search_notes', 'read_note', 'slow'], self.audit, self.opener)

    def test_session_is_lazy_reused_and_closed_and_whitelist_hides_tools(self):
        async def run():
            server = self.server()
            self.assertEqual(self.opens, 0)
            definitions = await server.definitions()
            self.assertEqual({item.name for item in definitions}, {'search_notes', 'read_note', 'slow'})
            self.assertFalse((await definitions[0].invoke({'query': 'synthetic'})).get('isError', False))
            await server.invoke('search_notes', {'query': 'again'})
            await server.close()
            await server.close()
            self.assertEqual((self.opens, self.closes), (1, 1))
            with self.assertRaisesRegex(RuntimeError, '已关闭'):
                await server.connection.request('list_tools')
        asyncio.run(run())
        logs = self.store.get_audit_logs(self.cid)
        self.assertEqual([item['status'] for item in logs], ['success', 'success'])
        self.assertEqual(self.evidence.snapshot()[1]['failed_searches'], 2)

    def test_unauthorized_tool_never_connects_and_invalid_arguments_never_execute(self):
        async def run():
            server = self.server()
            denied = await server.invoke('forbidden', {'query': 'x'})
            self.assertTrue(denied['isError'])
            self.assertEqual(self.opens, 0)
            invalid = await server.invoke('read_note', {'query': 123})
            self.assertTrue(invalid['isError'])
            self.assertEqual(self.calls, [])
            await server.close()
        asyncio.run(run())
        self.assertEqual(len(self.store.get_audit_logs(self.cid)), 1)
        self.assertEqual(self.store.get_audit_logs(self.cid)[0]['status'], 'failed')

    def test_failure_is_audited_once_and_private_error_is_not_returned(self):
        async def run():
            server = self.server()
            result = await server.invoke('read_note', {'query': 'synthetic'})
            self.assertTrue(result['isError'])
            self.assertNotIn('private-provider-token', str(result))
            await server.close()
        asyncio.run(run())
        logs = self.store.get_audit_logs(self.cid)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]['status'], 'failed')
        self.assertNotIn('private-provider-token', str(logs))
        self.assertEqual(self.evidence.snapshot()[1]['failed_searches'], 1)

    def test_cancelled_call_is_audited_and_transport_is_closed(self):
        async def run():
            server = self.server()
            self.started = asyncio.Event()
            task = asyncio.create_task(server.invoke('slow', {'query': 'synthetic'}))
            await self.started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            await server.close()
            self.assertEqual(self.closes, 1)
        asyncio.run(run())
        logs = self.store.get_audit_logs(self.cid)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]['error'], 'MCP 工具没有返回执行结果')

    def test_slow_call_times_out_with_guidance_for_the_model(self):
        async def run():
            server = ExternalToolServer('notes', {'type': 'http', 'url': 'unused'},
                                        ['search_notes', 'read_note', 'slow'], self.audit, self.opener, call_timeout=0.05)
            self.started = asyncio.Event()
            result = await server.invoke('slow', {'query': 'synthetic'})
            self.assertTrue(result['isError'])
            self.assertIn('没有返回结果', result['content'][0]['text'])
            self.assertIn('缩小范围', result['content'][0]['text'])
            self.assertFalse((await server.invoke('search_notes', {'query': 'after'})).get('isError', False))
            await server.close()
            self.assertEqual(self.closes, 1)
        asyncio.run(run())
        logs = self.store.get_audit_logs(self.cid)
        self.assertEqual([item['error'] for item in logs], ['MCP 工具调用超时', None])

    def test_actual_stdio_transport_uses_only_synthetic_echo_server(self):
        source = '''from mcp.server.fastmcp import FastMCP
server = FastMCP("synthetic")
@server.tool()
def echo(query: str) -> str:
    return query
server.run(transport="stdio")
'''
        async def run():
            async with open_mcp_session({'type': 'stdio', 'command': sys.executable, 'args': ['-c', source]}) as session:
                listing = await session.list_tools()
                self.assertEqual([tool.name for tool in listing.tools], ['echo'])
                result = await session.call_tool('echo', {'query': '合成文本'})
                self.assertFalse(result.isError)
                self.assertEqual(result.content[0].text, '合成文本')
        asyncio.run(run())

    def test_official_langchain_adapter_preserves_whitelist_errors_and_single_audit(self):
        async def run():
            server = self.server()
            try:
                tools = {tool.name: tool for tool in await server.to_langchain()}
                self.assertNotIn('mcp__notes__forbidden', tools)
                for name, arguments in [('search_notes', {'query': 'synthetic'}),
                                        ('read_note', {'query': 'synthetic'}),
                                        ('read_note', {'query': 123})]:
                    result = await tools[f'mcp__notes__{name}'].ainvoke({
                        'type': 'tool_call', 'id': 'synthetic', 'name': f'mcp__notes__{name}', 'args': arguments})
                    self.assertEqual(result.status, 'success' if name == 'search_notes' else 'error')
                    self.assertNotIn('private-provider-token', str(result.content))
                self.assertEqual([name for name, _ in self.calls], ['search_notes', 'read_note'])
            finally:
                await server.close()
            self.assertEqual((self.opens, self.closes), (1, 1))
        asyncio.run(run())
        self.assertEqual([log['status'] for log in self.store.get_audit_logs(self.cid)], ['success', 'failed', 'failed'])
