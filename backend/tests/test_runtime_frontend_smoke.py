"""Local built-UI smoke with synthetic API replies. No real backend/data/model/site."""
import json
import os
from pathlib import Path
import unittest
from urllib.parse import urlsplit
from unittest.mock import patch

from playwright.sync_api import sync_playwright, expect
from starlette.staticfiles import StaticFiles

from app.platform.browser import BROWSER_DIRECTORY
from app.platform.browser_runtime import browser_choice
from synthetic_application_site import SiteServer, create_site
from test_runtime_ui_contract import USAGE


DIST = Path(__file__).resolve().parents[2] / 'frontend/dist'
BROWSER_PATH = Path(os.getenv('PLAYWRIGHT_BROWSERS_PATH', str(BROWSER_DIRECTORY)))
CHOICE = browser_choice(BROWSER_PATH, None)


@unittest.skipUnless(DIST.joinpath('index.html').exists() and CHOICE['available'], 'Build frontend and install a test browser first')
class RuntimeFrontendSmokeTests(unittest.TestCase):
    def setUp(self):
        site = create_site()
        site.mount('/', StaticFiles(directory=DIST, html=True))
        self.server = SiteServer(site)
        self.server.__enter__()
        self.addCleanup(lambda: self.server.__exit__())
        environment = patch.dict(os.environ, {'PLAYWRIGHT_BROWSERS_PATH': str(BROWSER_PATH)})
        environment.start()
        self.addCleanup(environment.stop)
        self.playwright = sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        self.browser = self.playwright.chromium.launch(headless=True,
            **({'channel': CHOICE['channel']} if CHOICE['channel'] != 'chromium' else {}))
        self.addCleanup(self.browser.close)
        self.context = self.browser.new_context(viewport={'width': 1280, 'height': 900})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.set_default_timeout(8000)
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.agent = {'id': 'synthetic', 'name': '合成助手', 'description': '仅用于本地 UI 验收', 'platform_capabilities': []}
        self.conversations = [{'id': 'original', 'agent_id': 'synthetic', 'archived': True,
                               'created_at': '2026-10-21T10:00:00', 'title': '合成历史'}]
        self.histories = {'original': [{'role': 'user', 'content': '合成目标，不得提交。'}, {'role': 'assistant', 'content': '合成历史回答。'}]}
        self.creates, self.streams, self.unexpected = [], [], []
        self.page.route('**/*', self.route)

    def route(self, route):
        request = route.request
        if request.url.startswith(self.server.origin + '/'):
            route.continue_()
            return
        if not request.url.startswith('http://localhost:8000/api/'):
            self.unexpected.append(request.url)
            route.abort()
            return
        headers = {'access-control-allow-origin': self.server.origin,
                   'access-control-allow-headers': '*', 'access-control-allow-methods': '*'}
        if request.method == 'OPTIONS':
            route.fulfill(status=200, headers=headers)
            return
        path = urlsplit(request.url).path
        data = None
        if path == '/api/agents':
            data = [self.agent]
        elif path == '/api/agents/synthetic/conversations':
            data = self.conversations
        elif path == '/api/conversations':
            body = request.post_data_json
            self.creates.append(body)
            cid = f'new-{len(self.creates)}'
            self.conversations.insert(0, {'id': cid, 'agent_id': 'synthetic', 'archived': False,
                'created_at': '2026-10-21T10:00:00', 'title': '合成请求'})
            self.histories[cid] = []
            data = {'conversation_id': cid}
        elif path.endswith('/messages/stream'):
            cid = path.split('/')[3]
            self.streams.append(cid)
            events = [{'type': 'tool_started', 'call_id': 'one', 'tool_name': 'mcp__synthetic__read'},
                {'type': 'tool_finished', 'call_id': 'one', 'tool_name': 'mcp__synthetic__read', 'success': True},
                {'type': 'delta', 'content': '合成回答，尚未提交。'}, {'type': 'usage', 'usage': USAGE}, {'type': 'done'}]
            self.histories[cid].extend([{'role': 'user', 'content': request.post_data_json['content']},
                {'role': 'assistant', 'content': events[2]['content'], 'usage': USAGE, 'tool_activity': events[:2]}])
            route.fulfill(status=200, headers={**headers, 'content-type': 'text/event-stream'},
                          body=''.join('data: ' + json.dumps(event, ensure_ascii=False) + '\n\n' for event in events))
            return
        elif path.endswith('/messages'):
            data = self.histories[path.split('/')[3]]
        elif path.endswith(('/actions', '/files')) or path == '/api/tracking':
            data = []
        elif path == '/api/brief':
            data = {'date': '2026-10-21', 'total': 0, 'sections': []}
        else:
            self.unexpected.append(path)
            route.fulfill(status=404, headers=headers, json={'detail': 'Synthetic API route is missing'})
            return
        route.fulfill(status=200, headers=headers, json=data)

    def open(self):
        self.page.goto(self.server.origin, wait_until='networkidle')
        expect(self.page.get_by_label('输入消息')).to_be_enabled()

    def tool(self, name):
        """Header shortcuts fold into the “工具” menu when the main column is narrow."""
        toggle = self.page.locator('.headerToolsToggle')
        if toggle.is_visible() and toggle.get_attribute('aria-expanded') != 'true':
            toggle.click()
        self.page.get_by_role('button', name=name, exact=True).click()

    def test_send_streams_reply_usage_survives_reload_and_layout_fits_phones(self):
        self.open()
        expect(self.page.get_by_role('button', name='默认运行时', exact=True)).to_have_count(0)
        expect(self.page.locator('.newRuntimeOptions')).to_have_count(0)
        self.page.get_by_label('输入消息').fill('合成请求')
        self.page.get_by_role('button', name='发送消息', exact=True).click()
        expect(self.page.get_by_text('合成回答，尚未提交。', exact=True)).to_be_visible()
        self.assertEqual(self.creates, [{'agent_id': 'synthetic'}])
        details = self.page.locator('.runtimeDetails')
        expect(details.locator('summary')).to_contain_text('输入 未提供')
        details.locator('summary').click()
        expect(details).to_contain_text('已返回')
        self.page.reload(wait_until='networkidle')
        expect(self.page.locator('.runtimeDetails summary')).to_contain_text('输入 未提供')
        expect(self.page.get_by_role('button', name='复制工作摘要到新会话', exact=True)).to_have_count(0)
        self.assertEqual(self.streams, ['new-1'])
        self.page.set_viewport_size({'width': 390, 'height': 844})
        expect(self.page.get_by_text('合成回答，尚未提交。', exact=True)).to_be_visible()
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        self.assertEqual(self.errors, [])
        self.assertEqual(self.unexpected, [])

    def test_archived_conversation_is_read_only_with_a_way_to_start_over(self):
        self.open()
        item = self.page.locator('.historyItem', has_text='合成历史')
        expect(item.locator('.runtimeBadge')).to_have_text('只读')
        item.click()
        expect(self.page.get_by_text('合成历史回答。', exact=True)).to_be_visible()
        expect(self.page.locator('.archivedNotice')).to_contain_text('只能查看')
        expect(self.page.get_by_label('输入消息')).to_be_disabled()
        self.page.locator('.archivedNotice').get_by_role('button', name='新建会话继续').click()
        expect(self.page.locator('.archivedNotice')).to_have_count(0)
        expect(self.page.get_by_label('输入消息')).to_be_enabled()
        self.assertEqual(self.streams, [])
        self.assertEqual(self.errors, [])
        self.assertEqual(self.unexpected, [])
