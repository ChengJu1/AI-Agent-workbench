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

    def test_daily_brief_lists_what_needs_attention_today(self):
        from datetime import date, timedelta
        from app.kits.job_search.brief import build_brief
        today = date(2026, 10, 21)
        d = lambda n: (today + timedelta(days=n)).isoformat()
        rows = [
            {'id': 'a', 'company': '过期', 'position': '', 'stage': 'saved', 'deadline': d(-2), 'next_event_at': '', 'next_event': '', 'applied_at': '', 'has_kit': False},
            {'id': 'b', 'company': '今天', 'position': '后端', 'stage': 'preparing', 'deadline': d(0), 'next_event_at': '', 'next_event': '', 'applied_at': '', 'has_kit': False},
            {'id': 'c', 'company': '快了', 'position': '', 'stage': 'saved', 'deadline': d(3), 'next_event_at': '', 'next_event': '', 'applied_at': '', 'has_kit': False},
            {'id': 'd', 'company': '笔试', 'position': '', 'stage': 'test', 'deadline': '', 'next_event_at': d(1) + ' 19:00', 'next_event': '在线笔试', 'applied_at': '', 'has_kit': True},
            {'id': 'e', 'company': '久等', 'position': '', 'stage': 'applied', 'deadline': d(0), 'next_event_at': '', 'next_event': '', 'applied_at': d(-20) + ' 10:00', 'has_kit': True},
            {'id': 'f', 'company': '结束', 'position': '', 'stage': 'rejected', 'deadline': d(0), 'next_event_at': d(0) + ' 10:00', 'next_event': '面试', 'applied_at': '', 'has_kit': True},
        ]
        brief = build_brief(rows, self.services.kits['applications'].applications.database, today)
        sections = {s['id']: [(i['ref'], i['detail']) for i in s['items']] for s in brief['sections']}
        self.assertEqual(sections['due'], [('a', '已过截止 2 天，还没投递'), ('b', '今天截止')])
        self.assertEqual(sections['soon'], [('c', '2026-10-24 截止')])
        self.assertEqual(sections['events'], [('d', '明天 19:00 在线笔试')])
        self.assertEqual(sections['kit'], [('b', '还没有资料包')])
        self.assertEqual(sections['follow_up'], [('e', '投递 20 天没有进展，可以查一下状态')])
        self.assertNotIn('waiting', sections)
        self.assertEqual(brief['total'], 6)
        self.assertEqual(self.client.get('/api/brief').json()['total'], 0)

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
        draft = self.services.kits['applications'].profiles.save(type('R', (), {'data': self.services.kits['applications'].profiles.reviewed(self.profile['id'], 1), 'name': 'x', 'source_file_id': None,
                                                           'expected_version': 1})(), self.profile['id'], review_state='draft')
        with self.assertRaises(ServiceError):
            self.tool('application_prepare_kit', application_id=item['id'], profile_id=self.profile['id'], profile_version=draft['version'],
                      items=[{'label': '姓名', 'source': {'kind': 'profile', 'ref': 'basics.name', 'version': draft['version']}}])

    def test_tailored_resume_is_a_new_draft_and_cannot_invent_facts(self):
        period = lambda y1, y2: {'start': {'precision': 'month', 'year': y1, 'month': 7}, 'end': {'precision': 'month', 'year': y2, 'month': 9}}
        base = {'basics': {'name': '张三', 'email': 'zhangsan@example.com'}, 'education': PROFILE['data']['education'],
                'experience': [{'organization': '合成公司', 'title': '后端实习', 'period': period(2023, 2023), 'description': '写接口'},
                               {'organization': '示例实验室', 'title': '研究助理', 'period': period(2022, 2022), 'description': '整理数据'}],
                'skills': ['Python', 'SQL', 'Excel']}
        profile = self.client.post('/api/profiles', json={'name': '主简历', 'data': base}).json()
        item = self.tool('application_save', company='合成科技', position='后端开发', jd='负责 Python 后端与数据库设计')
        self.assertTrue(self.tool('application_list')['applications'][0]['has_jd'])
        tailored = {**base, 'experience': [{**base['experience'][0], 'description': '用 Python 设计并实现订单接口，优化 SQL 查询'}],
                    'skills': ['Python', 'SQL']}
        match = {'score': 78, 'matched': ['Python', 'SQL'], 'missing': ['Redis'], 'suggestions': ['补充性能优化的量化结果']}
        result = self.tool('application_tailor_resume', application_id=item['id'], profile_id=profile['id'], profile_version=1, data=tailored, match=match)
        draft = self.client.get(f"/api/profiles/{result['draft_profile_id']}").json()
        self.assertEqual((draft['review_state'], draft['name']), ('draft', '主简历 · 合成科技 后端开发版'))
        self.assertEqual(self.client.get(f"/api/profiles/{profile['id']}").json()['latest_version'], 1)  # The original is untouched.
        saved = self.client.get(f"/api/applications/{item['id']}").json()
        self.assertEqual((saved['tailoring']['score'], saved['tailoring']['missing']), (78, ['Redis']))
        # Facts cannot be added or changed: dates, new entries, new skills, contact details.
        for change in ({'experience': [{**base['experience'][0], 'period': period(2023, 2024)}]},
                       {'experience': base['experience'] + [{'organization': '虚构大厂', 'title': '算法', 'period': period(2024, 2024)}]},
                       {'skills': ['Python', 'Kubernetes']},
                       {'basics': {'name': '张三', 'email': 'other@example.com'}}):
            with self.assertRaises(ServiceError):
                self.tool('application_tailor_resume', application_id=item['id'], profile_id=profile['id'], profile_version=1,
                          data={**base, **change}, match=match)

    def test_interview_prep_is_stored_on_the_application(self):
        item = self.add()
        self.tool('application_save_interview_prep', application_id=item['id'], note='按 JD 整理', questions=[
            {'category': '技术', 'question': '如何优化慢查询？', 'points': ['先看执行计划', '再加索引'], 'based_on': 'JD：数据库设计'},
            {'category': '反问', 'question': '团队的技术栈？', 'points': ['了解日常工作']}])
        prep = self.client.get(f"/api/applications/{item['id']}").json()['interview_prep']
        self.assertEqual([q['category'] for q in prep['questions']], ['技术', '反问'])
        self.assertTrue(self.client.get('/api/applications').json()[0]['has_prep'])
        with self.assertRaises(Exception):
            self.tool('application_save_interview_prep', application_id=item['id'], questions=[{'category': '闲聊', 'question': 'x', 'points': ['y']}])

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
