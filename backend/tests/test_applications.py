"""Application ledger: records, stages, copy-ready kits, and a read-only form read in real headless Chromium."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from fastapi.testclient import TestClient
from synthetic_application_site import SiteServer, add_component_form, add_vendor_form, create_site
from app.application import create_app
from app.config import Settings
from app.container import build_services
from app.errors import ServiceError
from app.models.api import CreateAgentRequest
from app.platform.browser import BROWSER_DIRECTORY, BrowserService
from app.platform.browser_runtime import browser_choice
from app.storage.database import Database

AVAILABLE = browser_choice(Path(os.getenv('PLAYWRIGHT_BROWSERS_PATH', str(BROWSER_DIRECTORY))), None)['available']
PROFILE = {'name': '合成候选人', 'data': {
    'basics': {'name': '张三', 'email': 'zhangsan@example.com', 'phone': '13812345678'},
    'education': [{'school': '合成大学', 'degree': '本科', 'major': '计算机', 'period': {
        'start': {'precision': 'month', 'year': 2020, 'month': 9}, 'end': {'precision': 'month', 'year': 2024, 'month': 6}}}],
    'skills': ['Python', 'SQL']}}


class LocalHttp:
    def __init__(self, allowed):
        self.allowed = allowed

    def validate(self, url):
        if f'{urlsplit(url).scheme}://{urlsplit(url).netloc}' != self.allowed:
            raise ServiceError('测试环境仅能访问本地合成网站。', 403)

    def request(self, url, method='GET', headers=None, body=None, **kwargs):
        self.validate(url)
        response = httpx.request(method, url, headers=headers, content=body, follow_redirects=False, trust_env=False, timeout=10)
        return {'url': url, 'status': response.status_code, 'headers': list(response.headers.multi_items()), 'body': response.content}


class Harness(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.services = build_services(Settings(database_path=Path(folder.name) / 'apps.db'))
        self.client = TestClient(create_app(services=self.services))
        self.addCleanup(self.client.close)
        self.agent = self.services.registry.create(CreateAgentRequest(name='投递助手', description='本地验收', system_prompt='仅测试',
                                                                      platform_capabilities=['files', 'browser', 'applications']))
        self.cid = self.services.store.create(self.agent.id)
        self.profile = self.client.post('/api/profiles', json=PROFILE).json()

    def tool(self, name, **arguments):
        return self.services.platform.execute(self.cid, name, arguments)

    def add(self, **extra):
        response = self.client.post('/api/applications', json={'company': '合成科技', 'position': '算法工程师', 'url': 'https://jobs.example.com/1', **extra})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()


class LedgerTests(Harness):
    def test_records_stages_and_history(self):
        item = self.add(deadline='2026-10-30')
        self.assertEqual((item['stage'], item['stage_label']), ('saved', '待投递'))
        self.assertEqual(self.client.post('/api/applications', json={'company': '另一家', 'url': 'https://jobs.example.com/1'}).status_code, 409)
        # Edits need the current revision; stale ones are refused.
        body = {'company': '合成科技', 'position': '算法工程师', 'url': 'https://jobs.example.com/1', 'deadline': '2026-11-01'}
        self.assertEqual(self.client.put(f"/api/applications/{item['id']}", json=body).status_code, 422)
        edited = self.client.put(f"/api/applications/{item['id']}", json={**body, 'expected_revision': item['revision']}).json()
        self.assertEqual(edited['deadline'], '2026-11-01')
        self.assertEqual(self.client.put(f"/api/applications/{item['id']}", json={**body, 'expected_revision': item['revision']}).status_code, 409)
        applied = self.client.post(f"/api/applications/{item['id']}/stage", json={'expected_revision': edited['revision'], 'stage': 'applied'}).json()
        self.assertEqual(applied['stage'], 'applied')
        self.assertRegex(applied['applied_at'], r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$')
        self.assertEqual([e['body']['action'] for e in applied['events']], ['created', 'edited', 'stage'])
        self.assertEqual(self.client.post('/api/applications', json={'company': 'x', 'next_event_at': '2026-11-02 14:00'}).status_code, 422)
        self.assertEqual(self.client.delete(f"/api/applications/{item['id']}").json(), {'deleted': True})
        self.assertEqual(self.client.get('/api/applications').json(), [])

    def test_calendar_export_lists_open_deadlines_and_upcoming_events(self):
        self.add(company='合成;科技,一', deadline='2026-10-30')
        self.add(company='已投公司', url='https://jobs.example.com/2', deadline='2026-10-30')
        applied = next(a for a in self.client.get('/api/applications').json() if a['company'] == '已投公司')
        self.client.post(f"/api/applications/{applied['id']}/stage", json={'expected_revision': applied['revision'], 'stage': 'applied'})
        self.add(company='笔试公司', url='https://jobs.example.com/3', next_event_at='2026-11-02 19:00', next_event='在线笔试')
        response = self.client.get('/api/applications/calendar.ics')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers['content-type'].startswith('text/calendar'))
        body = response.text
        self.assertEqual(body.count('BEGIN:VEVENT'), 2)  # The applied job's deadline no longer matters.
        self.assertIn('DTSTART;VALUE=DATE:20261030', body)
        self.assertIn('SUMMARY:投递截止：合成\\;科技\\,一 · 算法工程师', body)
        self.assertIn('DTSTART:20261102T190000', body)
        self.assertIn('TRIGGER:-PT1H', body)
        self.assertTrue(all(len(line.encode()) <= 75 for line in body.split('\r\n')))

    def test_agent_updates_only_named_fields_and_never_infers_submission(self):
        item = self.tool('application_save', company='合成科技', position='算法', deadline='2026-10-30')
        self.assertEqual(item['stage'], 'saved')
        updated = self.tool('application_save', application_id=item['id'], next_event_at='2026-11-05 19:00', next_event='笔试', stage='test')
        self.assertEqual((updated['deadline'], updated['position'], updated['stage'], updated['next_event']), ('2026-10-30', '算法', 'test', '笔试'))
        self.assertEqual([a['company'] for a in self.tool('application_list')['applications']], ['合成科技'])

    def test_kit_from_reviewed_profile_with_flags(self):
        item = self.add()
        profiles = self.tool('application_profiles')['profiles']
        self.assertEqual(profiles[0]['data']['basics']['name'], '张三')
        profile = {'kind': 'profile', 'version': 1}
        kit = self.tool('application_prepare_kit', application_id=item['id'], profile_id=self.profile['id'], profile_version=1, items=[
            {'label': '姓名', 'source': {**profile, 'ref': 'basics.name'}},
            {'label': '入学时间', 'source': {**profile, 'ref': 'education.0.period.start'}, 'transform': 'date:month:/'},
            {'label': '最高学历', 'source': {**profile, 'ref': 'education.0.degree'}, 'transform': 'option:大学本科'},
            {'label': '期望城市', 'source': {'kind': 'user', 'ref': 'city'}, 'value': '深圳'},
            {'label': '自我评价', 'source': {'kind': 'inferred', 'ref': 'intro'}, 'value': '熟悉 Python 与 SQL。'}])
        self.assertEqual(kit['stage'], 'preparing')
        saved = self.client.get(f"/api/applications/{item['id']}").json()
        rows = {i['label']: (i['value'], i['flag']) for i in saved['kit']['items']}
        self.assertEqual(rows, {'姓名': ('张三', ''), '入学时间': ('2020/09', ''), '最高学历': ('大学本科', 'converted'),
                                '期望城市': ('深圳', 'chat'), '自我评价': ('熟悉 Python 与 SQL。', 'draft')})
        # The user can rewrite a draft; the edit is marked and logged without its text.
        edited = self.client.post(f"/api/applications/{item['id']}/kit", json={'expected_revision': saved['revision'], 'index': 4, 'value': '改写后的评价'}).json()
        self.assertEqual((edited['kit']['items'][4]['value'], edited['kit']['items'][4]['edited']), ('改写后的评价', True))
        self.assertNotIn('改写后的评价', str(edited['events']))
        # Facts are never invented: a missing path or an unreviewed draft profile is refused.
        with self.assertRaises(ServiceError):
            self.tool('application_prepare_kit', application_id=item['id'], profile_id=self.profile['id'], profile_version=1,
                      items=[{'label': '电话', 'source': {**profile, 'ref': 'basics.wechat'}}])
        draft = self.services.profiles.save(type('R', (), {'data': self.services.profiles.reviewed(self.profile['id'], 1), 'name': 'x', 'source_file_id': None,
                                                           'expected_version': 1})(), self.profile['id'], review_state='draft')
        with self.assertRaises(ServiceError):
            self.tool('application_prepare_kit', application_id=item['id'], profile_id=self.profile['id'], profile_version=draft['version'],
                      items=[{'label': '姓名', 'source': {'kind': 'profile', 'ref': 'basics.name', 'version': draft['version']}}])

    def test_old_task_capability_becomes_the_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Database(Path(folder) / 'm.db')
            database.initialize()
            with database.connection() as connection:
                connection.execute('''INSERT INTO agent_platform_capabilities VALUES ('a1', '["browser", "tasks"]')''')
            database.initialize()
            with database.connection() as connection:
                [row] = connection.execute('SELECT capabilities FROM agent_platform_capabilities').fetchall()
        self.assertEqual(row[0], '["browser", "applications"]')


@unittest.skipUnless(AVAILABLE, 'Playwright Chromium is not installed')
class ReadOnlyFormTests(Harness):
    def open(self, site, path):
        http = LocalHttp(site.origin)
        self.services.platform.browser = BrowserService(self.services.platform.files, http=http, url_validator=http.validate, headless=True)
        self.addCleanup(self.services.platform.browser.close)
        return self.tool('browser_open', url=site.origin + path)['session_id']

    def test_vendor_form_without_known_classes_becomes_a_kit_in_page_order(self):
        with SiteServer(add_vendor_form(create_site())) as site:
            session = self.open(site, '/apply3')
            fields = {f['label']: f for f in self.tool('application_read_form', session_id=session)['fields']}
            # Names come from the neighbouring element, not the "请输入" placeholder; "*" marks required; plain divs are dropdowns.
            self.assertEqual({k: (fields[k]['type'], fields[k]['required']) for k in ('姓名', '手机号码', '民族', '籍贯', '毕业时间', '通讯地址', '附件简历')},
                             {'姓名': ('text', True), '手机号码': ('text', True), '民族': ('custom_select', True), '籍贯': ('custom_select', True),
                              '毕业时间': ('custom_select', True), '通讯地址': ('text', False), '附件简历': ('file', False)})
            with patch('app.platform.files.parse_document', side_effect=lambda suffix, data: data.decode()):
                resume = self.services.platform.files.upload(self.cid, 'resume.txt', b'synthetic')
            item = self.add(url=site.origin + '/apply3')
            profile = {'kind': 'profile', 'version': 1}
            self.tool('application_prepare_kit', application_id=item['id'], profile_id=self.profile['id'], profile_version=1, session_id=session, items=[
                {'key': fields['学校名称']['key'], 'source': {**profile, 'ref': 'education.0.school'}},
                {'key': fields['姓名']['key'], 'source': {**profile, 'ref': 'basics.name'}},
                {'key': fields['手机号码']['key'], 'source': {**profile, 'ref': 'basics.phone'}},
                {'key': fields['毕业时间']['key'], 'source': {**profile, 'ref': 'education.0.period.end'}, 'transform': 'date:month'},
                {'key': fields['附件简历']['key'], 'source': {'kind': 'file', 'ref': resume['id']}}])
            kit = self.client.get(f"/api/applications/{item['id']}").json()['kit']
            rows = [(i['label'], i['value'], i['flag']) for i in kit['items']]
            # Page order, with the required fields the profile cannot answer listed for the user.
            self.assertEqual(rows[:2], [('附件简历', 'resume.txt', 'file'), ('姓名', '张三', '')])
            self.assertEqual({r[0] for r in rows if r[2] == 'missing'}, {'民族', '户口所在地', '籍贯', '期望月薪'})
            self.assertEqual(kit['form_url'], site.origin + '/apply3')
            # Reading and drafting never touched the employer site.
            self.assertEqual(site.app.state.submissions, [])
            self.assertEqual(self.services.tool_store.get_pending_actions(self.cid), [])
            browser = self.services.platform.browser
            import asyncio
            marks = asyncio.run_coroutine_threadsafe(browser.sessions[session]['page'].evaluate(
                "() => [...document.querySelectorAll('*')].filter(e => [...e.attributes].some(a => a.name.startsWith('data-wb'))).length"), browser.loop).result()
            self.assertEqual(marks, 0)

    def test_component_form_types(self):
        with SiteServer(add_component_form(create_site())) as site:
            session = self.open(site, '/apply2')
            fields = {f['label']: f['type'] for f in self.tool('application_read_form', session_id=session)['fields']}
            self.assertEqual({k: fields[k] for k in ('简历附件', '姓名', '性别', '政治面貌', '籍贯', '入学时间', '自我评价')},
                             {'简历附件': 'file', '姓名': 'text', '性别': 'radio', '政治面貌': 'custom_select', '籍贯': 'cascader', '入学时间': 'date', '自我评价': 'textarea'})
            self.assertEqual(site.app.state.submissions, [])


if __name__ == '__main__':
    unittest.main()
