"""Foundation capability grants, scoped files, real parsers, public HTTP and approvals."""
import asyncio
import io
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from app.application import create_app
from app.config import Settings
from app.container import build_services
from app.errors import ServiceError
from app.models.api import CreateAgentRequest
from app.models.builds import BuildPlan
from app.platform.files import parse_document
from app.platform.network import PublicBackend, PublicHttp, validate_url
from app.platform.web import WebService


class FakeBrowser:
    def __init__(self):
        self.executed = 0
    def close(self):
        pass
    def status(self):
        return {'available': True, 'headed': False}
    def call(self, method, conversation_id, *args):
        if method == 'prepare':
            return {'session_id': args[0], 'snapshot_id': args[1], 'url': 'https://employer.example/jobs/1',
                    'title': 'Synthetic application', 'operations': args[2], 'fingerprint': 'same', 'expires_at': time.time() + 300}
        if method == 'execute':
            self.executed += 1
            return {'completed_operations': 1, 'message': '已执行本地合成操作，请核对回执。'}
        return {'ok': True}


class PlatformCapabilitiesTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.settings = Settings(database_path=Path(temporary.name)/'test.db')
        self.services = build_services(self.settings)
        self.addCleanup(self.services.platform.browser.close)
        self.fake = FakeBrowser(); self.services.platform.browser = self.fake
        self.client = TestClient(create_app(services=self.services)); self.addCleanup(self.client.close)
        self.agent = self.services.registry.create(CreateAgentRequest(name='合成能力测试', description='仅用于测试', system_prompt='使用授权工具并等待确认。', platform_capabilities=['files', 'web', 'browser']))
        self.cid = self.services.store.create(self.agent.id)

    def prepare(self):
        return self.services.platform.execute(self.cid, 'browser_prepare_actions', {'session_id': 'browser_'+'1'*32, 'snapshot_id': 'snapshot', 'operations': [{'kind': 'click', 'element_id': 'e_1', 'label': 'Synthetic submit'}]})

    def test_capability_only_agent_and_grant_persist(self):
        self.assertEqual(self.agent.tools, [])
        response = self.client.get('/api/agents')
        found = next(agent for agent in response.json() if agent['id'] == self.agent.id)
        self.assertEqual(found['platform_capabilities'], ['files', 'web', 'browser'])
        response = self.client.put(f'/api/agents/{self.agent.id}/capabilities', json={'capabilities': ['files']})
        self.assertEqual(response.status_code, 200)
        fresh = build_services(self.settings); self.addCleanup(fresh.platform.browser.close)
        self.assertEqual(fresh.registry.get_agent(self.agent.id).platform_capabilities, ['files'])
        with self.assertRaises(ServiceError):
            self.services.platform.execute(self.cid, 'web_search', {'query': 'Python job'})
        self.assertEqual(self.client.put(f'/api/agents/{self.agent.id}/capabilities', json={'capabilities': ['shell']}).status_code, 422)

    def test_file_attachment_scope_and_no_arbitrary_host_path(self):
        with patch('app.platform.files.parse_document', return_value='Synthetic candidate Python SQL'):
            result = self.client.post(f'/api/conversations/{self.cid}/files', files={'file': ('../../cv.txt', b'Synthetic', 'text/plain')})
        self.assertEqual(result.status_code, 201, result.text)
        info = result.json(); self.assertEqual(info['filename'], 'cv.txt')
        read = self.services.platform.execute(self.cid, 'read_file', {'file_id': info['id'], 'limit': 9})
        self.assertEqual(read['text'], 'Synthetic')
        self.assertEqual(read['next_offset'], 9)
        other = self.services.store.create(self.agent.id)
        self.assertEqual(self.client.get(f'/api/conversations/{other}/files/{info["id"]}').status_code, 404)
        with self.assertRaises(ServiceError):
            self.services.platform.execute(self.cid, 'read_file', {'file_id': '/etc/passwd'})
        self.client.put(f'/api/agents/{self.agent.id}/capabilities', json={'capabilities': []})
        self.assertEqual(self.client.get(f'/api/conversations/{self.cid}/files/{info["id"]}').status_code, 403)

    def test_file_validation_and_agent_scope(self):
        for name, content in [('resume.exe', b'x'), ('resume.txt', b''), ('resume.pdf', b'x'*2_000_001)]:
            response = self.client.post(f'/api/conversations/{self.cid}/files', files={'file': (name, content)})
            self.assertEqual(response.status_code, 422)
        builtin = self.services.store.create('policy_qa_assistant')
        self.assertEqual(self.client.post(f'/api/conversations/{builtin}/files', files={'file': ('cv.txt', b'x')}).status_code, 403)
        self.assertEqual(self.client.get('/api/conversations/missing/files').status_code, 404)

    def test_only_granted_tools_reach_the_runtime_and_revocation_is_checked(self):
        self.services.registry.bind_platform(self.agent.id, ['files'])
        agent = self.services.registry.get_agent(self.agent.id)
        turn = self.services.deep_agents.tool_services.prepare(self.cid, agent, None, None)
        names = {definition.name for definition in turn.groups['workbench_platform']}
        self.assertIn('read_file', names)
        self.assertNotIn('web_search', names)
        self.assertEqual(turn.external, {})
        self.services.registry.bind_platform(self.agent.id, [])
        with self.assertRaises(ServiceError):
            self.services.platform.execute(self.cid, 'list_files', {})

    def test_browser_prepare_does_not_execute_then_confirmation_is_once(self):
        result = self.prepare(); action = result['pending_action']
        self.assertEqual(self.fake.executed, 0)
        self.assertEqual(self.prepare()['pending_action']['id'], action['id'])
        response = self.client.post(f'/api/pending-actions/{action["id"]}/decision', json={'approved': True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.fake.executed, 1)
        self.assertEqual(response.json()['status'], 'approved')
        duplicate = self.client.post(f'/api/pending-actions/{action["id"]}/decision', json={'approved': True})
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(self.fake.executed, 1)
        self.assertTrue(all(log['tool_type'] == 'browser' for log in self.services.tool_store.get_audit_logs(self.cid)))

    def test_cancel_or_revoked_capability_never_executes(self):
        action = self.prepare()['pending_action']
        response = self.client.post(f'/api/pending-actions/{action["id"]}/decision', json={'approved': False})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.fake.executed, 0)
        action = self.prepare()['pending_action']
        self.services.registry.bind_platform(self.agent.id, [])
        response = self.client.post(f'/api/pending-actions/{action["id"]}/decision', json={'approved': True})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.fake.executed, 0)
        self.assertEqual(self.services.tool_store.get_pending_action(action['id'])['status'], 'failed')

    def test_browser_failure_is_not_retried_or_reported_as_submission_success(self):
        action = self.prepare()['pending_action']
        original = self.fake.call
        def fail(method, *args):
            if method == 'execute':
                raise ServiceError('页面已变化，未执行。', 409)
            return original(method, *args)
        self.fake.call = fail
        response = self.client.post(f'/api/pending-actions/{action["id"]}/decision', json={'approved': True})
        self.assertEqual(response.status_code, 502)
        self.assertIn('页面已变化', response.json()['detail'])
        self.assertEqual(self.fake.executed, 0)
        self.assertNotIn('提交成功', self.services.store.get_messages(self.cid)[-1]['content'])

    def test_platform_only_build_requires_explicit_capability_approval(self):
        generator = AsyncMock()
        generator.generate.return_value = BuildPlan(status='ready', message='使用附件、网络和受控浏览器', name='秋招测试助手', description='先推荐再确认', system_prompt='读取简历，搜索公开岗位，投递前等待确认。', capabilities=['files', 'web', 'browser'])
        self.services.agent_builds.generator = generator
        response = self.client.post('/api/agent-builds', json={'request_id': str(uuid4()), 'message': '创建秋招测试助手'})
        build = self.services.agent_builds.store.get(response.json()['id'])
        self.assertEqual(build['status'], 'ready')
        path = f'/api/agent-builds/{build["id"]}/publish'
        self.assertEqual(self.client.post(path, json={'expected_revision': 1}).status_code, 422)
        response = self.client.post(path, json={'expected_revision': 1, 'approved_capabilities': ['files', 'web', 'browser']})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()['platform_capabilities'], ['files', 'web', 'browser'])
        self.assertEqual(self.services.registry.get_agent(response.json()['id']).platform_capabilities, ['files', 'web', 'browser'])

    def test_pending_browser_approval_survives_model_failure(self):
        owner = self

        class FailingModel(FakeListChatModel):
            def bind_tools(self, tools, **kwargs):
                return self

            async def _astream(self, messages, **kwargs):
                owner.prepare()  # A pending action is created mid-turn, then the model fails.
                raise RuntimeError('synthetic model failure')
                yield

        self.services.deep_agents.model_factory = lambda: FailingModel(responses=['unused'])
        async def collect():
            prepared = self.services.conversations.prepare(self.cid, 'local fixture')
            return [event async for event in self.services.conversations.stream(self.cid, 'local fixture', prepared)]
        with patch('app.runtime.deep_agents.logger.exception'):
            events = asyncio.run(collect())
        self.assertTrue(any(event['type'] == 'approval_required' for event in events))
        self.assertEqual(events[-1]['type'], 'error')
        self.assertEqual(self.fake.executed, 0)


class PublicNetworkTest(unittest.TestCase):
    def resolve(self, ip):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443))]

    def test_private_and_credentials_urls_rejected(self):
        for ip in ['127.0.0.1', '10.1.2.3', '169.254.169.254', '192.168.1.1', '0.0.0.0', '::1']:
            with patch('socket.getaddrinfo', return_value=self.resolve(ip)), self.assertRaises(ServiceError):
                validate_url('https://public-looking.example/path')
        for url in ['file:///etc/passwd', 'http://user:secret@example.com/', 'http://example.com:8000/', 'javascript:alert(1)']:
            with self.assertRaises(ServiceError):
                validate_url(url)

    def test_socket_connect_uses_validated_ip_not_second_dns_lookup(self):
        with patch('socket.getaddrinfo', return_value=self.resolve('93.184.216.34')), patch('httpcore.SyncBackend.connect_tcp', return_value='stream') as connect:
            self.assertEqual(PublicBackend().connect_tcp('example.com', 443), 'stream')
            self.assertEqual(connect.call_args.args[:2], ('93.184.216.34', 443))
        with patch('socket.getaddrinfo', return_value=self.resolve('127.0.0.1')), patch('httpcore.SyncBackend.connect_tcp') as connect:
            with self.assertRaises(ServiceError):
                PublicBackend().connect_tcp('rebound.example', 443)
            connect.assert_not_called()

    def test_web_extraction_keeps_real_url_and_pagination(self):
        class Http:
            def request(self, url):
                return {'url': url, 'status': 200, 'headers': [('content-type', 'text/html')], 'body': b'<title>Jobs</title><script>evil()</script><h1>Python engineer</h1><a href="/apply">Apply</a>'}
        result = WebService(http=Http()).read('https://example.com/jobs', limit=8)
        self.assertEqual(result['url'], 'https://example.com/jobs')
        self.assertEqual(result['title'], 'Jobs')
        self.assertEqual(result['citation'], '[网页原文](https://example.com/jobs)')
        self.assertEqual(result['links'][0]['url'], 'https://example.com/apply')
        self.assertNotIn('evil', result['text'])
        self.assertEqual(result['next_offset'], 8)

    def test_search_outage_is_explicit_and_does_not_create_results(self):
        def fail(*args):
            raise RuntimeError('offline')
        with self.assertRaises(ServiceError):
            WebService(search=fail).search('Python 校招')


@unittest.skipUnless(os.getenv('WORKBENCH_RUN_SANDBOX_TESTS') == '1', 'Real parser subprocess needs host sandbox access')
class FileParserIntegrationTest(unittest.TestCase):
    def test_text_and_docx_and_pdf_parse_real_content(self):
        self.assertIn('Python', parse_document('.txt', '合成简历 Python SQL'.encode()))
        from docx import Document
        doc = Document(); doc.add_paragraph('Synthetic Resume Python SQL'); data = io.BytesIO(); doc.save(data)
        self.assertIn('Python', parse_document('.docx', data.getvalue()))
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        writer = PdfWriter(); page = writer.add_blank_page(200, 200)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        stream = DecodedStreamObject(); stream.set_data(b'BT /F1 12 Tf 10 100 Td (Synthetic Resume Python SQL) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        data = io.BytesIO(); writer.write(data)
        self.assertIn('Python', parse_document('.pdf', data.getvalue()))

    def test_invalid_and_empty_documents_are_rejected(self):
        for suffix, data in [('.pdf', b'not a PDF'), ('.docx', b'not a DOCX'), ('.txt', b'\xff\xfe\x00')]:
            with self.assertRaises(ServiceError):
                parse_document(suffix, data)

class BrowserGuardTest(unittest.TestCase):
    def setUp(self):
        from app.platform.browser import BrowserService
        self.browser = BrowserService(files=object(), headless=False)
        self.cid, self.sid = 'conversation', 'browser_'+'2'*32
        self.page = type('Page', (), {'url': 'https://example.com/apply'})()
        self.page.is_closed = lambda: False
        self.page.title = AsyncMock(return_value='Synthetic Application')
        self.handle = type('Handle', (), {})()
        self.handle.evaluate = AsyncMock(return_value={'tag': 'input', 'type': 'text', 'label': 'Synthetic name'})
        self.handle.fill = AsyncMock()
        self.handle.click = AsyncMock()
        self.browser.sessions[self.sid] = {'conversation_id': self.cid, 'origin':'https://example.com', 'touched': time.time(), 'page': self.page,
            'snapshot_id': 'current', 'fingerprint': 'same', 'handles': {'e_1': self.handle}, 'manual_until': 0, 'writes': False}
        self.browser._fingerprint = AsyncMock(return_value='same')

    def test_stale_snapshot_and_changed_page_rejected_before_planning(self):
        args = (self.cid, self.sid, 'old', [{'kind': 'fill', 'element_id': 'e_1', 'value': 'Synthetic'}])
        with self.assertRaises(ServiceError):
            asyncio.run(self.browser._prepare(*args))
        self.browser._fingerprint.return_value = 'changed'
        with self.assertRaises(ServiceError):
            asyncio.run(self.browser._prepare(self.cid, self.sid, 'current', args[-1]))
        self.handle.fill.assert_not_called()

    def test_custom_div_button_can_be_planned_but_does_not_execute(self):
        self.handle.evaluate.return_value = {'tag':'div','type':'','role':'button','clickable':True,'disabled':False,'label':'合成按钮'}
        plan = asyncio.run(self.browser._prepare(self.cid,self.sid,'current',[{'kind':'click','element_id':'e_1'}]))
        self.assertEqual(plan['operations'][0]['label'],'合成按钮')
        self.handle.fill.assert_not_awaited()
        self.handle.click.assert_not_awaited()

    def test_disabled_or_noninteractive_div_cannot_be_planned(self):
        for disabled,clickable in ((True,True),(False,False)):
            self.handle.evaluate.return_value = {'tag':'div','type':'','clickable':clickable,'disabled':disabled,'label':'合成文本'}
            with self.assertRaises(ServiceError):
                asyncio.run(self.browser._prepare(self.cid,self.sid,'current',[{'kind':'click','element_id':'e_1'}]))

    def test_model_cannot_prepare_password_or_other_conversation(self):
        self.handle.evaluate.return_value = {'tag': 'input', 'type': 'password', 'label': 'Password'}
        with self.assertRaises(ServiceError):
            asyncio.run(self.browser._prepare(self.cid, self.sid, 'current', [{'kind': 'fill', 'element_id': 'e_1', 'value': 'must-not-store'}]))
        with self.assertRaises(ServiceError):
            asyncio.run(self.browser._session('other', self.sid))

    def test_expired_approval_never_fills(self):
        plan = {'session_id': self.sid, 'snapshot_id': 'current', 'fingerprint': 'same', 'expires_at': 0,
                'operations': [{'kind': 'fill', 'element_id': 'e_1', 'value': 'Synthetic'}]}
        with self.assertRaises(ServiceError):
            asyncio.run(self.browser._execute(self.cid, plan))
        self.handle.fill.assert_not_called()

    def test_partial_failure_closes_write_window_and_does_not_retry(self):
        self.handle.evaluate.return_value = True
        self.handle.click = AsyncMock(side_effect=TimeoutError())
        plan = {'session_id': self.sid, 'snapshot_id': 'current', 'fingerprint': 'same', 'expires_at': time.time()+60,
                'operations': [{'kind': 'fill', 'element_id': 'e_1', 'value': 'Synthetic'}, {'kind': 'click', 'element_id': 'e_1'}]}
        with self.assertRaisesRegex(ServiceError, '已完成 1 个操作'):
            asyncio.run(self.browser._execute(self.cid, plan))
        self.handle.fill.assert_awaited_once()
        self.handle.click.assert_awaited_once()
        self.assertFalse(self.browser.sessions[self.sid]['writes'])

class HostProtectionTest(unittest.TestCase):
    def test_untrusted_host_cannot_read_local_api(self):
        client = TestClient(create_app(services=object()))
        self.addCleanup(client.close)
        self.assertEqual(client.get('/api/health', headers={'host': 'attacker.example'}).status_code, 400)
        self.assertEqual(client.get('/api/health').status_code, 200)

class RedirectProtectionTest(unittest.TestCase):
    def test_redirect_to_private_destination_is_not_requested(self):
        from contextlib import contextmanager
        class Pool:
            def __init__(self, *args, **kwargs): self.requests = 0
            def __enter__(self): return self
            def __exit__(self, *args): return None
            @contextmanager
            def stream(self, method, url, **kwargs):
                self.requests += 1
                yield type('Reply', (), {'status': 302, 'headers': [(b'location', b'http://127.0.0.1/secret')]})()
        pool = Pool()
        def resolve(host, *args, **kwargs):
            ip = '127.0.0.1' if host == '127.0.0.1' else '93.184.216.34'
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 80))]
        with patch('socket.getaddrinfo', side_effect=resolve), patch('httpcore.ConnectionPool', return_value=pool):
            with self.assertRaises(ServiceError):
                PublicHttp().request('https://example.com/redirect')
        self.assertEqual(pool.requests, 1)

class SearchPrivacyTest(unittest.TestCase):
    def test_contact_details_not_sent_to_search_provider(self):
        provider = AsyncMock()
        for query in ['Python candidate@example.com', '上海 13800000000 Python']:
            with self.assertRaises(ServiceError):
                WebService(search=provider).search(query)
        provider.assert_not_called()

    def test_browser_origin_canonicalizes_default_ports(self):
        from app.platform.browser import origin
        self.assertEqual(origin('https://Example.com:443/jobs'), origin('https://example.com/jobs'))
        self.assertEqual(origin('http://example.com:80/jobs'), 'http://example.com')

class UnicodeWebAddressTest(unittest.TestCase):
    def test_unicode_path_is_sent_as_valid_uri(self):
        from contextlib import contextmanager
        class Pool:
            url = None
            def __enter__(self): return self
            def __exit__(self, *args): return None
            @contextmanager
            def stream(self, method, url, **kwargs):
                self.url = url
                yield type('Reply', (), {'status': 200, 'headers': [], 'iter_stream': lambda s: iter([b'ok'])})()
        pool = Pool()
        with patch('app.platform.network.validate_url', side_effect=lambda url: __import__('urllib.parse', fromlist=['urlsplit']).urlsplit(url)), patch('httpcore.ConnectionPool', return_value=pool):
            PublicHttp().request('https://example.com/上海?岗位=Python')
        self.assertIn('%E4%B8%8A%E6%B5%B7', pool.url)
        self.assertTrue(pool.url.isascii())

class BrowserHeaderCanonicalizationTest(unittest.TestCase):
    def test_browser_headers_replace_defaults_case_insensitively(self):
        from contextlib import contextmanager
        from urllib.parse import urlsplit
        class Pool:
            outgoing = None
            def __enter__(self): return self
            def __exit__(self, *args): return None
            @contextmanager
            def stream(self, method, url, **kwargs):
                self.outgoing = kwargs['headers']
                yield type('Reply', (), {'status':200,'headers':[], 'iter_stream':lambda self:iter([b'ok'])})()
        pool = Pool()
        with patch('app.platform.network.validate_url', side_effect=urlsplit), patch('httpcore.ConnectionPool', return_value=pool):
            PublicHttp().request('https://example.com/', headers={'user-agent':'SyntheticBrowser/1.0','hOsT':'must-not-forward','Accept-Encoding':'gzip'})
        user_agents = [value for key,value in pool.outgoing.items() if key.lower() == 'user-agent']
        self.assertEqual(user_agents, ['SyntheticBrowser/1.0'])
        self.assertEqual([value for key,value in pool.outgoing.items() if key.lower() == 'accept-encoding'], ['identity'])
        self.assertFalse(any(key.lower() == 'host' for key in pool.outgoing))
