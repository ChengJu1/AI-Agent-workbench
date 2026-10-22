"""Intent persistence is separate from real executions and status observations."""
import concurrent.futures
import unittest
from unittest.mock import MagicMock
from pydantic import ValidationError
from app.errors import ServiceError
from app.models.tracking import WorkItemSave
from app.container import build_services
import test_tracking as tracking_fixtures


class WorkItemTests(unittest.TestCase):
    setUp = tracking_fixtures.TrackingTests.setUp
    ready = tracking_fixtures.TrackingTests.ready

    def definition(self, **changes):
        return WorkItemSave(**({'key':'SYN-001', 'title':'合成对象办理', 'target_url':'https://employer.example/jobs/1'} | changes))

    def save(self, **changes):
        return self.services.platform.execute(self.cid, 'save_work_item', self.definition(**changes).model_dump())

    def test_persist_deduplicate_and_compare_revision(self):
        self.ready()
        item = self.save()
        self.assertEqual(self.save()['id'], item['id'])
        self.assertEqual(item['executions'], [])
        self.assertEqual(len(self.tracking.items.list()), 1)
        with self.assertRaises(ServiceError): self.save(note='unexpected overwrite')
        changed = self.save(item_id=item['id'], expected_revision=1, state='blocked', note='页面未找到对应表单', next_step='核对原始入口')
        self.assertEqual(changed['revision'], 2)
        self.assertEqual(len(changed['events']), 2)
        with self.assertRaises(ServiceError): self.save(item_id=item['id'], expected_revision=1)
        restarted = build_services(self.settings)
        self.addCleanup(restarted.platform.browser.close)
        self.assertEqual(restarted.tracking.items.get(item['id'])['state'], 'blocked')
        self.assertEqual(self.tracking.store.records(), [])

    def test_scope_grants_and_input_cannot_claim_success(self):
        self.ready(); item = self.save()
        other = self.client.post('/api/conversations', json={'agent_id': self.agent.id}).json()['conversation_id']
        with self.assertRaises(ServiceError):
            self.services.platform.execute(other, 'save_work_item', self.definition(item_id=item['id'], expected_revision=1).model_dump())
        with self.assertRaises(ServiceError): self.tracking.items.get(item['id'], 'other-agent')
        for changes in ({'state':'submitted'}, {'state':'blocked'}, {'item_id':item['id']}, {'target_url':'https://name:password@example.com'}, {'key':' '}):
            with self.assertRaises(ValidationError):
                self.definition(**changes)
        self.services.registry.bind_platform(self.agent.id, ['browser'])
        with self.assertRaises(ServiceError): self.save()

    def test_real_action_link_pending_cancelled_and_target_lock(self):
        self.ready(); item = self.save()
        args = {'session_id':'browser_'+'1'*32, 'snapshot_id':'snapshot', 'operations':[{'kind':'click', 'element_id':'e_1'}], 'work_item_id':item['id']}
        action = self.services.platform.execute(self.cid, 'browser_prepare_actions', args)['pending_action']
        self.assertEqual(self.services.platform.execute(self.cid, 'browser_prepare_actions', args)['pending_action']['id'], action['id'])
        actual = self.tracking.items.get(item['id'])
        self.assertEqual(actual['state'], 'planned')
        self.assertEqual(actual['executions'][0]['state'], 'pending')
        self.services.approvals.decide(action['id'], False)
        self.assertEqual(self.tracking.items.get(item['id'])['executions'][0]['state'], 'cancelled')
        body = self.definition(item_id=item['id'], expected_revision=1).model_dump()
        body['target_url'] = 'https://employer.example/jobs/2'
        with self.assertRaises(ServiceError): self.services.platform.execute(self.cid, 'save_work_item', body)
        self.save(item_id=item['id'], expected_revision=1, state='cancelled')
        with self.assertRaises(ServiceError): self.services.platform.execute(self.cid, 'browser_prepare_actions', args)
        self.assertEqual(self.services.platform.browser.executed, 0)

    def test_atomic_link_scope_and_revision_race(self):
        self.ready(); item = self.save()
        def update():
            try: return self.save(item_id=item['id'], expected_revision=1, note='并发更新')['revision']
            except ServiceError as e: return e.status_code
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            self.assertEqual(sorted(pool.map(lambda _:update(), range(2))), [2,409])
        other = self.client.post('/api/conversations', json={'agent_id':self.agent.id}).json()['conversation_id']
        with self.assertRaises(ServiceError):
            self.services.tool_store.create_pending_action(other, self.agent.id, 'workbench_platform', 'browser_actions', {'work_item_id':item['id'], 'url':item['target_url']}, tool_type='browser')
        self.assertEqual(self.tracking.store.records(), [])
        with self.services.store.database.connection() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM pending_actions').fetchone()[0], 0)

    def test_linked_observation_does_not_turn_plan_into_claimed_success(self):
        self.ready(); item = self.save()
        args = {'session_id':'browser_'+'1'*32, 'snapshot_id':'snapshot', 'operations':[{'kind':'click','element_id':'e_1'}], 'work_item_id':item['id']}
        pending = self.services.platform.execute(self.cid,'browser_prepare_actions',args)['pending_action']
        self.services.approvals.decide(pending['id'],True)
        from app.models.tracking import TrackingDefinition
        definition = TrackingDefinition(title='合成对象状态',url='https://example.com/status',anchor='SYN-001',record_id='run_'+pending['id'],rules=[{'status':'已提交','keywords':['已提交']}])
        task = self.tracking.create(self.cid,definition)
        self.tracking.check(task['id'])
        actual = self.tracking.items.get(item['id'])
        self.assertEqual(actual['state'],'planned')
        self.assertEqual(actual['executions'][0]['state'],'confirmed')
        self.assertEqual(actual['tracking'][0]['business_status'],'已提交')
        self.assertEqual(len(actual['events']),1)

    def test_api_and_tool_discovery(self):
        self.ready()
        body = self.definition().model_dump() | {'conversation_id':self.cid}
        saved = self.client.post('/api/work-items', json=body)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(len(self.client.get('/api/work-items').json()), 1)
        self.assertEqual(self.client.get('/api/work-items/'+saved.json()['id']).json()['events'][0]['revision'], 1)
        self.assertEqual(self.client.post('/api/work-items', json=body|{'state':'submitted'}).status_code, 422)
        from mcp_test_server import create_platform_server
        _, tools = create_platform_server(self.services.platform, self.cid, self.agent)
        self.assertIn('mcp__workbench_platform__save_work_item', tools)

    def test_browser_retry_is_persisted_even_without_model_saving_again(self):
        self.ready(); item = self.save(state='blocked', note='上次页面未读到')
        self.services.platform.browser.call = MagicMock(side_effect=ServiceError('合成加载超时',504))
        with self.assertRaises(ServiceError):
            self.services.platform.execute(self.cid,'browser_open',{'url':item['target_url']})
        saved = self.tracking.items.get(item['id'])
        self.assertEqual(saved['last_attempt']['status'],'failed')
        self.assertEqual(saved['attempts'][0]['error'],'合成加载超时')
        self.assertEqual(saved['revision'],1)
        self.services.platform.browser.call.side_effect = None
        self.services.platform.browser.call.return_value = {'session_id':'test','http_status':200,'text':'合成公开内容','elements':[]}
        result = self.services.platform.execute(self.cid,'browser_open',{'url':item['target_url']})
        self.assertEqual(result['work_item_id'],item['id'])
        saved = self.tracking.items.get(item['id'])
        self.assertEqual(len(saved['attempts']),2)
        self.assertEqual(saved['last_attempt']['status'],'readable')
        self.assertEqual(saved['state'],'blocked')  # Reading is not a business completion.

    def test_read_attempt_does_not_guess_across_conversations_or_shared_urls(self):
        self.ready(); item = self.save()
        other = self.client.post('/api/conversations',json={'agent_id':self.agent.id}).json()['conversation_id']
        self.services.platform.execute(other,'browser_open',{'url':item['target_url']})
        self.assertEqual(self.tracking.items.get(item['id'])['attempts'],[])
        self.save(key='SYN-002', title='另一个对象使用同一入口')
        self.services.platform.execute(self.cid,'browser_open',{'url':item['target_url']})
        self.assertTrue(all(not self.tracking.items.get(row['id'])['attempts'] for row in self.tracking.items.list()))

    def test_context_uses_only_current_conversation_and_current_attempt(self):
        self.ready(); item = self.save()
        other = self.client.post('/api/conversations',json={'agent_id':self.agent.id}).json()['conversation_id']
        self.services.platform.execute(other,'save_work_item',self.definition(title='OTHER_PRIVATE_TITLE').model_dump())
        self.services.platform.browser.call = MagicMock(side_effect=ServiceError('合成失败',504))
        with self.assertRaises(ServiceError):self.services.platform.execute(self.cid,'browser_open',{'url':item['target_url']})
        prepared = self.services.conversations.prepare(self.cid,'重试一下')
        try:
            self.assertIn(item['id'],prepared.context)
            self.assertIn('合成失败',prepared.context)
            self.assertNotIn('OTHER_PRIVATE_TITLE',prepared.context)
        finally:self.services.conversations.release(self.cid,prepared)

if __name__ == '__main__': unittest.main()
