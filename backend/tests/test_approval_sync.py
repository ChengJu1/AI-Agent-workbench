"""UI must be able to reconcile writes that returned errors or completed elsewhere."""
import unittest
from app.errors import ServiceError
import test_platform_capabilities as fixtures

class ApprovalSyncTests(unittest.TestCase):
    setUp = fixtures.PlatformCapabilitiesTest.setUp
    prepare = fixtures.PlatformCapabilitiesTest.prepare

    def test_failed_decision_remains_readable_even_when_pending_list_is_empty(self):
        action=self.prepare()['pending_action']
        original=self.fake.call
        def fail(method,*args):
            if method=='execute': raise ServiceError('合成操作已停止，未执行。',409)
            return original(method,*args)
        self.fake.call=fail
        path=f'/api/pending-actions/{action["id"]}/decision'
        self.assertEqual(self.client.post(path,json={'approved':True}).status_code,502)
        detail=self.client.get(f'/api/conversations/{self.cid}/actions/{action["id"]}')
        self.assertEqual(detail.status_code,200)
        self.assertEqual(detail.json()['status'],'failed')
        self.assertIn('未执行',detail.json()['result']['error'])
        self.assertEqual(self.client.get(f'/api/conversations/{self.cid}/pending-actions').json(),[])
        self.assertEqual(self.client.get(f'/api/conversations/{self.cid}/actions').json()[0]['status'],'failed')
        duplicate=self.client.post(path,json={'approved':True})
        self.assertEqual(duplicate.status_code,409)
        self.assertIn('已处理',duplicate.json()['detail'])
        self.assertEqual(self.fake.executed,0)

    def test_result_lookup_is_conversation_scoped_and_executing_is_visible(self):
        action=self.prepare()['pending_action']
        self.services.tool_store.update_pending_action(action['id'],'executing')
        other=self.services.store.create(self.agent.id)
        self.assertEqual(self.client.get(f'/api/conversations/{other}/actions/{action["id"]}').status_code,404)
        current=self.client.get(f'/api/conversations/{self.cid}/actions/{action["id"]}').json()
        self.assertEqual(current['status'],'executing')
        self.assertEqual(self.fake.executed,0)

    def test_recent_history_does_not_hide_older_active_actions(self):
        original=self.prepare()['pending_action']
        store=self.services.tool_store
        for _ in range(55):
            key=store.create_pending_action(self.cid,self.agent.id,'workbench_platform','browser_actions',{})
            row=store.get_pending_action(key)
            store.finish_action(row,'cancelled','合成记录',expected_status='pending')
        rows=self.client.get(f'/api/conversations/{self.cid}/actions').json()
        self.assertEqual(len(rows),51)
        self.assertTrue(any(r['id']==original['id'] and r['status']=='pending' for r in rows))
