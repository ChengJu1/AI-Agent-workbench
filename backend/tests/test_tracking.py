import asyncio
import concurrent.futures
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_agent_builder as fixtures
import test_platform_capabilities as platform_fixtures
from app.container import build_services
from app.errors import ServiceError
from app.models.agents import LoadedAgent,PermissionsManifest
from app.models.tracking import TrackingDefinition,TrackingControl
from app.platform.browser import BrowserService
from app.services.tracking_service import TrackingService
from app.tools.platform_tools import create_platform_server,FileUpdate

class TrackingTests(unittest.TestCase):
    setUp=fixtures.BuilderTestCase.setUp
    def ready(self):
        self.agent=LoadedAgent(id='tracking-agent',name='跟踪助手',description='test',system_prompt='test',skills=[],tools=[],permissions=PermissionsManifest(dry_run_by_default=True),platform_capabilities=['files','web','browser','tracking'])
        self.services.registry.store.create(self.agent)
        self.cid=self.client.post('/api/conversations',json={'agent_id':self.agent.id}).json()['conversation_id']
        self.services.platform.browser=platform_fixtures.FakeBrowser()
        self.tracking=self.services.tracking
        self.web=self.services.platform.web
        self.web.read=MagicMock(return_value={'url':'https://example.com/status','title':'合成状态','text':'申请 SYN-001 已提交'})
    def definition(self,**extra):
        return TrackingDefinition(title='通用状态跟踪',url='https://example.com/status',anchor='SYN-001',interval_minutes=5,rules=[{'status':'已提交','keywords':['已提交']},{'status':'已结束','keywords':['已结束'],'terminal':True}],**extra)
    def task(self,**extra):return self.tracking.create(self.cid,self.definition(**extra))
    def upload(self,name='resume.txt',data=b'first'):
        with patch('app.platform.files.parse_document',side_effect=lambda suffix,data:data.decode()):return self.services.platform.files.upload(self.cid,name,data)

    def test_record_before_execute_not_inferred_success_duplicate_cancel(self):
        self.ready();platform=self.services.platform
        args={'session_id':'browser_'+'1'*32,'snapshot_id':'snapshot','operations':[{'kind':'click','element_id':'e_1'}]}
        action=platform.execute(self.cid,'browser_prepare_actions',args)['pending_action']
        self.assertEqual(self.tracking.store.records()[0]['state'],'pending')
        self.services.approvals.decide(action['id'],True)
        self.assertEqual(self.tracking.store.records()[0]['state'],'needs_verification')
        with self.assertRaises(ServiceError):self.services.approvals.decide(action['id'],True)
        self.assertEqual(len(self.tracking.store.records()),1)
        other=platform.execute(self.cid,'browser_prepare_actions',args)['pending_action'];self.services.approvals.decide(other['id'],False)
        self.assertEqual(self.tracking.store.record('run_'+other['id'])['state'],'cancelled')

    def test_paused_resume_unchanged_terminal_and_notification(self):
        self.ready();task=self.task();self.assertEqual(task['state'],'paused');self.assertIsNone(self.tracking.check())
        self.tracking.store.control(task['id'],TrackingControl(expected_revision=1,action='resume'))
        checked=self.tracking.check();self.assertEqual(checked['business_status'],'已提交');self.assertEqual(checked['unread'],1)
        self.assertGreater(checked['next_check_at'],time.time());self.assertEqual(self.tracking.check(task['id'])['unread'],1)
        self.web.read.return_value['text']='申请 SYN-001 已结束'
        done=self.tracking.check(task['id']);self.assertEqual(done['state'],'completed');self.assertIsNone(done['next_check_at']);self.assertEqual(done['unread'],2)

    def test_ambiguity_errors_and_revocation_preserve_status(self):
        self.ready();task=self.task();self.tracking.check(task['id'])
        self.web.read.return_value['text']='申请 SYN-001 已提交 已结束'
        ambiguous=self.tracking.check(task['id']);self.assertEqual(ambiguous['business_status'],'已提交');self.assertIn('唯一状态',ambiguous['last_error'])
        self.web.read.return_value['text']='SYN-001 已结束 SYN-001 已提交'
        blocked=self.tracking.check(task['id']);self.assertEqual(blocked['state'],'blocked');self.assertEqual(blocked['business_status'],'已提交')
        count=self.web.read.call_count;self.services.registry.bind_platform(self.agent.id,['tracking'])
        self.assertEqual(self.tracking.check(task['id'])['state'],'blocked');self.assertEqual(count,self.web.read.call_count)

    def test_restart_leases_and_pause_reject_stale_completions(self):
        self.ready();task=self.task();store=self.tracking.store
        old=store.claim(task['id'],now=10)
        with self.assertRaises(ServiceError):store.claim(task['id'],now=11)
        fresh=store.claim(task['id'],now=101);self.assertFalse(store.finish(old,'wrong','matched',{}));self.assertTrue(store.finish(fresh,'已提交','matched',{}))
        restored=build_services(self.settings).tracking.store.get(task['id']);self.assertEqual(restored['business_status'],'已提交');self.assertEqual(len(restored['checks']),1)
        claimed=store.claim(task['id']);store.control(task['id'],TrackingControl(expected_revision=restored['revision'],action='pause'));self.assertFalse(store.finish(claimed,'stale','matched',{}))

    def test_parallel_claim_scope_and_cross_conversation(self):
        self.ready();task=self.task()
        def claim():
            try:return self.tracking.store.claim(task['id'])
            except ServiceError:return None
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:claim(),range(4)))
        self.assertEqual(sum(r is not None for r in results),1)
        with self.assertRaises(ServiceError):self.tracking.store.get(task['id'],'other')
        _,allowed=create_platform_server(self.services.platform,self.cid,self.agent.model_copy(update={'platform_capabilities':['tracking']}))
        self.assertIn('mcp__workbench_platform__create_tracking',allowed);self.assertNotIn('mcp__workbench_platform__web_read',allowed)
        action=self.services.tool_store.create_pending_action(self.cid,self.agent.id,'workbench_platform','browser_actions',{'operations':[]})
        other=self.client.post('/api/conversations',json={'agent_id':self.agent.id}).json()['conversation_id']
        with self.assertRaises(ServiceError):self.tracking.create(other,self.definition(record_id='run_'+action))

    def test_file_versions_stale_update_and_scoping(self):
        self.ready();file=self.upload();files=self.services.platform.files
        with patch('app.platform.files.parse_document',side_effect=lambda suffix,data:data.decode()):
            updated=files.update(self.cid,file['id'],1,'new.txt',b'second');self.assertEqual(updated['id'],file['id']);self.assertEqual(updated['version'],2)
            with self.assertRaises(ServiceError):files.update(self.cid,file['id'],1,'new.txt',b'third')
        self.assertEqual(files.raw(self.cid,file['id'],1)[1],b'first');self.assertEqual(len(files.versions(self.cid,file['id'])),2)
        other=self.client.post('/api/conversations',json={'agent_id':self.agent.id}).json()['conversation_id']
        with self.assertRaises(ServiceError):files.raw(other,file['id'],1)

    def test_local_changed_missing_relink_and_permission(self):
        self.ready();files=self.services.platform.files;original=self.settings.database_path.parent/'linked.txt';original.write_text('original')
        with patch('app.platform.files.parse_document',side_effect=lambda suffix,data:data.decode()):
            file=files.link_local(self.cid,str(original));original.write_text('changed');self.assertEqual(files.check(self.cid,file['id'])['resource_state'],'changed')
            with self.assertRaises(ServiceError):files.read(self.cid,file['id'])
            refreshed=files.execute_update(self.cid,files.prepare_update(self.cid,file['id'],1))['file'];self.assertEqual(refreshed['version'],2)
            moved=original.with_name('renamed.txt');original.rename(moved);self.assertEqual(files.check(self.cid,file['id'])['resource_state'],'missing')
            self.assertEqual(files.link_local(self.cid,str(moved),file['id'],2)['version'],3)
        with patch('app.platform.files.os.open',side_effect=PermissionError()):self.assertEqual(files.check(self.cid,file['id'])['resource_state'],'permission_denied')
        self.assertEqual(files.raw(self.cid,file['id'],1)[1],b'original')

    def test_update_file_waits_approval_and_forbids_host_path(self):
        self.ready();original=self.upload();replacement=self.upload('new.txt',b'second');platform=self.services.platform
        params={'file_id':original['id'],'expected_version':1,'replacement_file_id':replacement['id']};plan=platform.execute(self.cid,'update_file',params)
        self.assertEqual(platform.files.info(self.cid,original['id'])['version'],1)
        self.assertEqual(platform.execute(self.cid,'update_file',params)['pending_action']['id'],plan['pending_action']['id'])
        with patch('app.platform.files.parse_document',side_effect=lambda suffix,data:data.decode()):self.services.approvals.decide(plan['pending_action']['id'],True)
        self.assertEqual(platform.files.read(self.cid,original['id'])['text'],'second')
        with self.assertRaises(Exception):FileUpdate.model_validate({**params,'source_path':'/private/secret'})

    def test_browser_preflight_before_any_fill_and_restart_worker(self):
        self.ready();file=self.upload();files=self.services.platform.files;browser=BrowserService(files);page=MagicMock();handle=MagicMock();handle.fill=AsyncMock();sid='browser_'+'1'*32
        browser.sessions[sid]={'conversation_id':self.cid,'touched':time.time(),'page':page,'snapshot_id':'snap','fingerprint':'same','handles':{'e_1':handle},'writes':False};browser._fingerprint=AsyncMock(return_value='same')
        plan={'session_id':sid,'snapshot_id':'snap','fingerprint':'same','expires_at':time.time()+60,'operations':[{'kind':'fill','element_id':'e_1','value':'x'},{'kind':'upload','element_id':'e_2','file_id':file['id'],'file_version':1,'file_hash':file['content_hash']}]}
        with patch('app.platform.files.parse_document',return_value='updated'):files.update(self.cid,file['id'],1,'resume.txt',b'updated')
        with self.assertRaises(ServiceError):asyncio.run(browser._execute(self.cid,plan))
        handle.fill.assert_not_called()
        task=self.task();self.tracking.store.control(task['id'],TrackingControl(expected_revision=1,action='resume'));restarted=TrackingService(self.services.platform)
        async def run():
            await restarted.start()
            for _ in range(30):
                if restarted.store.get(task['id'])['last_checked_at']:break
                await asyncio.sleep(.02)
            await restarted.close()
        asyncio.run(run());self.assertEqual(restarted.store.get(task['id'])['business_status'],'已提交')

    def test_api_changes_pause_target_reset_and_stale_revision(self):
        self.ready();task=self.task();self.tracking.check(task['id'])
        payload={**self.definition().model_dump(),'anchor':'SYN-002','expected_revision':1}
        updated=self.client.put('/api/tracking/'+task['id'],json=payload)
        self.assertEqual(updated.status_code,200,updated.text)
        self.assertEqual(updated.json()['state'],'paused');self.assertEqual(updated.json()['business_status'],'')
        self.assertEqual(len(updated.json()['checks']),1)
        self.assertEqual(self.client.put('/api/tracking/'+task['id'],json=payload).status_code,409)
        self.assertEqual(self.client.post('/api/tracking/'+task['id']+'/control',json={'expected_revision':2,'action':'pause'}).status_code,200)
        self.assertEqual(self.client.get('/api/tracking').status_code,200)

    def test_file_api_updates_local_version_without_exposing_path_to_model(self):
        self.ready();path=self.settings.database_path.parent/'ui.txt';path.write_text('one')
        with patch('app.platform.files.parse_document',side_effect=lambda suffix,data:data.decode()):
            response=self.client.post(f'/api/conversations/{self.cid}/local-files',json={'path':str(path)})
            self.assertEqual(response.status_code,201,response.text);file=response.json();self.assertNotIn('source_path',file)
            path.write_text('two')
            self.assertEqual(self.client.get(f"/api/conversations/{self.cid}/files/{file['id']}/check").json()['resource_state'],'changed')
            update=self.client.post(f"/api/conversations/{self.cid}/files/{file['id']}/refresh",json={'expected_version':1})
            self.assertEqual(update.status_code,200,update.text);self.assertEqual(update.json()['version'],2)
            old=self.client.get(f"/api/conversations/{self.cid}/files/{file['id']}?version=1")
            self.assertEqual(old.json()['text'],'one')

    def test_browser_shutdown_cleans_up_after_transport_has_disconnected(self):
        self.ready();browser=BrowserService(self.services.platform.files)
        browser.call('close',self.cid,'missing')
        browser.sessions['synthetic']={'browser':MagicMock(close=AsyncMock(side_effect=RuntimeError('transport closed')))}
        driver=MagicMock(stop=AsyncMock(side_effect=RuntimeError('driver closed')));browser.driver=driver
        browser.close();browser.close()
        self.assertIsNone(browser.loop);self.assertIsNone(browser.driver);self.assertEqual(browser.sessions,{})
        driver.stop.assert_awaited_once()
