import asyncio
import base64
import time
import unittest
from unittest.mock import AsyncMock,MagicMock
from app.platform.browser import BrowserService
from app.errors import ServiceError
import test_tracking as fixtures

class BrowserPreviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.browser=BrowserService(None,headless=False)
        self.page=MagicMock(url='https://example.com/form',viewport_size={'width':1200,'height':800})
        self.page.screenshot=AsyncMock(return_value=b'synthetic-png')
        self.page.bring_to_front=AsyncMock()
        self.page.is_closed.return_value=False
        self.page.evaluate=AsyncMock(return_value=True)
        self.cdp=MagicMock(send=AsyncMock(return_value={'data':base64.b64encode(b'synthetic-png').decode()}))
        self.context=MagicMock(new_cdp_session=AsyncMock(return_value=self.cdp))
        self.handle=MagicMock()
        self.handle.is_visible=AsyncMock(return_value=True)
        self.handle.bounding_box=AsyncMock(return_value={'x':10,'y':20,'width':80,'height':30})
        self.handle.scroll_into_view_if_needed=AsyncMock()
        self.handle.click=AsyncMock()
        self.session={'id':'s','conversation_id':'c','page':self.page,'browser_name':'Google Chrome','touched':time.time(),'manual_until':0,'writes':False,'snapshot_id':'snap','handles':{'e':self.handle},'lock':asyncio.Lock()}
        self.browser.sessions['s']=self.session
        self.session['context']=self.context
        self.browser._fingerprint=AsyncMock(return_value='fingerprint')
        self.plan={'status':'pending','snapshot_id':'snap','fingerprint':'fingerprint','expires_at':time.time()+300,'operations':[{'kind':'click','element_id':'e','label':'合成按钮'}]}

    async def test_preview_is_read_only_and_preserves_action_snapshot(self):
        frame=await self.browser._preview('c','s',self.plan)
        self.assertEqual(base64.b64decode(frame['image'].split(',')[1]),b'synthetic-png')
        self.assertEqual(frame['plan_state'],'current')
        self.assertEqual(frame['target']['label'],'合成按钮')
        self.assertEqual(self.session['snapshot_id'],'snap')
        self.assertFalse(self.session['writes'])
        self.handle.click.assert_not_awaited();self.handle.scroll_into_view_if_needed.assert_not_awaited()
        self.page.screenshot.assert_not_awaited()
        self.cdp.send.assert_awaited_once_with('Page.captureScreenshot',{'format':'png','fromSurface':True,'captureBeyondViewport':False})

    async def test_takeover_pauses_all_screenshot_endpoints_and_dom_reads(self):
        before=await self.browser._preview('c','s')
        await self.browser._takeover('c','s',True,300)
        self.cdp.send.reset_mock();self.page.evaluate.reset_mock()
        self.browser._fingerprint.reset_mock()
        frame=await self.browser._preview('c','s',self.plan)
        raw=await self.browser._screenshot('c','s')
        self.assertTrue(frame['capture_paused']);self.assertEqual(frame['image'],before['image'])
        self.assertEqual(frame['captured_at'],before['captured_at']);self.assertEqual(raw,b'synthetic-png')
        self.cdp.send.assert_not_awaited();self.page.evaluate.assert_not_awaited();self.browser._fingerprint.assert_not_awaited()

    async def test_takeover_before_first_preview_does_not_capture_or_read_the_page(self):
        await self.browser._takeover('c','s',True,300)
        frame=await self.browser._preview('c','s')
        self.assertEqual(frame['captured_at'],0);self.assertTrue(frame['capture_paused'])
        self.context.new_cdp_session.assert_not_awaited();self.page.evaluate.assert_not_awaited()

    async def test_concurrent_preview_consumers_share_a_single_capture(self):
        entered,release=asyncio.Event(),asyncio.Event()
        async def capture(*args):
            entered.set();await release.wait();return {'data':base64.b64encode(b'one-frame').decode()}
        self.cdp.send.side_effect=capture
        first=asyncio.create_task(self.browser._preview('c','s'))
        await entered.wait();second=asyncio.create_task(self.browser._preview('c','s'))
        release.set();frames=await asyncio.gather(first,second)
        self.cdp.send.assert_awaited_once();self.assertEqual(frames[0]['image'],frames[1]['image'])

    async def test_takeover_duration_requires_explicit_valid_value_and_handoff_still_stops_it(self):
        start=time.time();await self.browser._takeover('c','s',True,300)
        self.assertGreaterEqual(self.session['manual_until'],start+300)
        for duration in [0,601,True,'300']:
            with self.assertRaises(ServiceError):await self.browser._takeover('c','s',True,duration)
        await self.browser._takeover('c','s',False)
        self.assertEqual(self.session['manual_until'],0)

    async def test_empty_target_page_is_explicit_instead_of_silent_white_preview(self):
        self.page.evaluate.return_value=False
        self.session['request_errors']=[{'host':'cdn.example.com','error':'合成资源被限制'}]
        frame=await self.browser._preview('c','s')
        self.assertEqual(frame['page_state'],'empty')
        self.assertEqual(frame['resource_warning'],'合成资源被限制')

    async def test_stale_plan_and_manual_takeover_never_show_wrong_target(self):
        self.browser._fingerprint.return_value='changed'
        result=await self.browser._preview('c','s',self.plan)
        self.assertEqual(result['plan_state'],'stale');self.assertIsNone(result['target'])
        with self.assertRaises(ServiceError):await self.browser._preview('c','s',self.plan,0,True)
        self.session['manual_until']=time.time()+60
        self.assertEqual((await self.browser._preview('c','s',self.plan))['plan_state'],'busy')
        self.handle.scroll_into_view_if_needed.assert_not_awaited()

    async def test_focus_only_scrolls_reviewed_target_and_respects_session_lock(self):
        await self.browser._dispatch('preview','c','s',self.plan,0,True)
        self.handle.scroll_into_view_if_needed.assert_awaited_once()
        async with self.session['lock']:
            frame=await asyncio.wait_for(self.browser._dispatch('preview','c','s',self.plan,0),timeout=.3)
            self.assertEqual(frame['plan_state'],'current')
            with self.assertRaises(ServiceError):await self.browser._dispatch('preview','c','s',self.plan,0,True)
        self.handle.click.assert_not_awaited()

    async def test_execution_progress_remains_visible_while_action_is_running(self):
        entered,release=asyncio.Event(),asyncio.Event()
        async def click(**kwargs):entered.set();await release.wait()
        self.handle.click=click
        self.handle.evaluate=AsyncMock(return_value=True)
        self.page.wait_for_load_state=AsyncMock()
        self.browser._read=AsyncMock(return_value={'text':'合成操作结果'})
        plan=self.plan|{'session_id':'s'}
        async def execute():
            async with self.session['lock']:return await self.browser._execute('c',plan)
        task=asyncio.create_task(execute())
        await asyncio.wait_for(entered.wait(),.5)
        frame=await asyncio.wait_for(self.browser._dispatch('preview','c','s',self.plan,0),.5)
        self.assertEqual(frame['progress']['phase'],'executing');self.assertIsNone(frame['target'])
        release.set();await task
        self.assertEqual(self.session['operation_progress']['phase'],'completed')

    async def test_other_conversation_cannot_see_preview_or_takeover(self):
        with self.assertRaises(ServiceError):await self.browser._preview('other','s')
        self.page.screenshot.assert_not_awaited()
        await self.browser._takeover('c','s',True)
        self.page.bring_to_front.assert_awaited_once()
        self.browser.headless=True
        with self.assertRaises(ServiceError):await self.browser._takeover('c','s',True)

    async def test_closed_window_is_removed_instead_of_returning_an_unusable_preview(self):
        self.session['browser']=MagicMock()
        self.session['browser'].close=AsyncMock()
        self.page.is_closed.return_value=True
        with self.assertRaises(ServiceError) as error:
            await self.browser._preview('c','s')
        self.assertEqual(error.exception.status_code,410)
        self.assertNotIn('s',self.browser.sessions)
        self.page.screenshot.assert_not_awaited()

    async def test_browser_list_omits_closed_windows(self):
        self.session['browser']=MagicMock()
        self.session['browser'].close=AsyncMock()
        self.page.is_closed.return_value=True
        self.assertEqual(await self.browser._list('c'),[])
        self.assertNotIn('s',self.browser.sessions)

    async def test_reload_preserves_sensitive_flag_and_never_repeats_a_write(self):
        self.session.update(origin='https://example.com',has_sensitive_data=True,request_errors=[{'error':'old'}])
        self.browser.validate_url=MagicMock()
        self.browser._navigate_and_read=AsyncMock(return_value={'text':'公开岗位页面'})
        await self.browser._reload('c','s')
        self.browser._navigate_and_read.assert_awaited_once_with('c','s','https://example.com/form')
        self.assertTrue(self.session['has_sensitive_data'])
        self.assertEqual(self.session['snapshot_id'],'')
        self.assertEqual(self.session['request_errors'],[])
        self.handle.click.assert_not_awaited()
        self.session['manual_until']=time.time()+60
        with self.assertRaises(ServiceError):await self.browser._reload('c','s')
        with self.assertRaises(ServiceError):await self.browser._reload('other','s')

    async def test_navigation_click_does_not_claim_private_data_was_entered(self):
        self.handle.evaluate=AsyncMock(return_value=True)
        self.page.wait_for_load_state=AsyncMock()
        self.browser._read=AsyncMock(return_value={'text':'登录页面','elements':[]})
        observed=[]
        async def click(**kwargs):observed.append(self.session.get('has_sensitive_data',False))
        self.handle.click=click
        await self.browser._execute('c',self.plan|{'session_id':'s'})
        self.assertEqual(observed,[False])
        self.assertFalse(self.session.get('has_sensitive_data',False))

    async def test_real_data_operations_and_existing_sensitive_session_remain_protected(self):
        self.handle.evaluate=AsyncMock(return_value=True)
        self.page.wait_for_load_state=AsyncMock()
        self.browser._read=AsyncMock(return_value={'text':'表单','elements':[]})
        self.handle.fill=AsyncMock()
        self.handle.click=AsyncMock()
        await self.browser._execute('c',self.plan|{'session_id':'s','operations':[{'kind':'fill','element_id':'e','value':'合成资料'}]})
        self.assertTrue(self.session['has_sensitive_data'])
        self.session['snapshot_id']='snap'
        await self.browser._execute('c',self.plan|{'session_id':'s'})
        self.assertTrue(self.session['has_sensitive_data'])

class PreviewApiTests(unittest.TestCase):
    setUp=fixtures.TrackingTests.setUp
    ready=fixtures.TrackingTests.ready
    def test_preview_requires_grant_and_same_conversation_action(self):
        self.ready();sid='browser_'+'1'*32
        pending=self.services.platform.execute(self.cid,'browser_prepare_actions',{'session_id':sid,'snapshot_id':'snapshot','operations':[{'kind':'click','element_id':'e_1'}]})['pending_action']
        path=f'/api/conversations/{self.cid}/browser/{sid}/preview'
        result=self.client.get(path,params={'action_id':pending['id']})
        self.assertEqual(result.status_code,200);self.assertEqual(result.headers['cache-control'],'no-store')
        bad=path.replace(sid,'browser_'+'2'*32)
        self.assertEqual(self.client.get(bad,params={'action_id':pending['id']}).status_code,404)
        self.assertEqual(self.client.get(path,params={'operation_index':12}).status_code,422)
        self.services.registry.bind_platform(self.agent.id,[])
        self.assertEqual(self.client.get(path).status_code,403)

    def test_reload_requires_browser_grant_and_returns_only_navigation_summary(self):
        from unittest.mock import patch
        self.ready()
        sid='browser_'+'1'*32
        result={'session_id':sid,'url':'https://example.com','text':'not-in-response','http_status':200}
        path=f'/api/conversations/{self.cid}/browser/{sid}/reload'
        with patch.object(self.services.platform.browser,'call',return_value=result) as call:
            response=self.client.post(path)
            self.assertEqual(response.status_code,200)
            self.assertNotIn('text',response.json())
            call.assert_called_once_with('reload',self.cid,sid)
            self.services.registry.bind_platform(self.agent.id,[])
            self.assertEqual(self.client.post(path).status_code,403)
            self.assertEqual(call.call_count,1)
