import time
import unittest
import asyncio
from unittest.mock import AsyncMock,MagicMock
from app.platform.browser_connections import BrowserConnections
from app.platform.browser import BrowserService
from app.platform.browser_resources import PublicResourceCache
from app.errors import ServiceError


class ConnectionTests(unittest.TestCase):
    def test_permissions_pin_exact_url_and_method_and_do_not_send_a_request(self):
        connections=BrowserConnections();page='https://example.com/login';url='https://cdn.example.com/login.js?v=1'
        connections.note(url,'GET','script',page)
        rows=connections.selected([connections.view(page)['pending'][0]['id']],page,False)
        connections.approve(rows)
        self.assertTrue(connections.permitted(url,'GET'))
        self.assertFalse(connections.permitted(url+'&extra=data','GET'))
        self.assertFalse(connections.permitted(url,'POST'))
        self.assertFalse(BrowserConnections().permitted(url,'GET'))

    def test_write_permission_requires_explicit_data_consent_and_is_revocable(self):
        connections=BrowserConnections();page='https://example.com/form';url='https://api.example.com/send'
        connections.note(url,'POST','xhr',page)
        id=connections.view(page)['pending'][0]['id']
        with self.assertRaises(ServiceError):connections.selected([id],page,False)
        old=connections.fingerprint()
        connections.approve(connections.selected([id],page,True))
        self.assertNotEqual(old,connections.fingerprint())
        self.assertEqual(connections.destinations(),['https://api.example.com'])
        connections.revoke();self.assertFalse(connections.permitted(url,'POST'))

    def test_expired_wrong_page_and_unknown_requests_cannot_be_approved(self):
        connections=BrowserConnections();page='https://example.com/form'
        connections.note('https://cdn.example.com/file','GET','fetch',page)
        row=connections.view(page)['pending'][0]
        for ids,p in [([row['id']],'https://example.com/other'),(['invented'],page),([row['id'],row['id']],page)]:
            with self.assertRaises(ServiceError):connections.selected(ids,p,False)
        connections.pending[('https://cdn.example.com/file','GET')]['expires_at']=time.time()-1
        with self.assertRaises(ServiceError):connections.selected([row['id']],page,False)

    def test_grant_expiry_changes_action_fingerprint(self):
        connections=BrowserConnections();page='https://example.com/form';url='https://api.example.com/send'
        connections.note(url,'POST','xhr',page)
        connections.approve(connections.selected([connections.view(page)['pending'][0]['id']],page,True))
        before=connections.fingerprint();connections.grants[(url,'POST')]=time.time()-1
        self.assertFalse(connections.permitted(url,'POST'))
        self.assertNotEqual(before,connections.fingerprint())


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.browser=BrowserService(None,http=MagicMock())
        self.browser.http.request.return_value={'status':200,'headers':[('content-type','text/javascript'),('set-cookie','synthetic=1')],'body':b'public script'}
        self.page=MagicMock(url='https://site.example.com/login')
        self.page.is_closed.return_value=False
        self.session={'id':'s','conversation_id':'c','page':self.page,'origin':'https://site.example.com',
            'touched':time.time(),'manual_until':0,'writes':False,'has_sensitive_data':True,'request_errors':[],
            'public_resources':PublicResourceCache(),'cached_resource_hits':0,'snapshot_id':'snap','handles':{},'lock':asyncio.Lock()}
        self.browser.sessions['s']=self.session
        self.connections=self.browser._connections(self.session)
        self.browser.validate_url=MagicMock()

    def route(self,method='GET',url='https://cdn.example.com/new-login.js',navigation=False):
        request=MagicMock(url=url,method=method,resource_type='script' if method=='GET' else 'xhr',post_data_buffer=b'synthetic-form')
        request.is_navigation_request.return_value=navigation
        request.all_headers=AsyncMock(return_value={'cookie':'synthetic-cookie','authorization':'synthetic-auth',
            'x-api-token':'synthetic-token','referer':'https://site.example.com/private','accept':'*/*','origin':'https://site.example.com'})
        return MagicMock(request=request,abort=AsyncMock(),fulfill=AsyncMock())

    def approve(self,route,allow_data=False):
        request=route.request
        self.connections.note(request.url,request.method,request.resource_type,self.page.url)
        row=next(row for row in self.connections.view(self.page.url)['pending'] if row['url']==request.url)
        self.connections.approve(self.connections.selected([row['id']],self.page.url,allow_data))

    async def test_unknown_new_resource_is_pending_and_not_sent(self):
        route=self.route()
        await self.browser._route_request(self.session,route)
        route.abort.assert_awaited_once();self.browser.http.request.assert_not_called()
        self.assertEqual(self.connections.view(self.page.url)['pending'][0]['url'],route.request.url)

    async def test_expired_takeover_blocks_same_site_preflight_and_reports_latest_reason(self):
        for index in range(20):
            self.browser._request_issue(self.session,{'host':'logs.example.com','path':f'/old/{index}','method':'POST','error':'old logs'})
        route=self.route('POST','https://site.example.com/api/Submission/CheckJobAd?private=synthetic')
        self.session['manual_until']=time.time()-1
        await self.browser._route_request(self.session,route)
        self.browser.http.request.assert_not_called()
        issue=self.session['request_errors'][-1]
        self.assertEqual(issue['code'],'manual_required')
        self.assertEqual(issue['path'],'/api/Submission/CheckJobAd')
        self.assertNotIn('synthetic',str(issue))
        self.assertEqual(len(self.session['request_errors']),20)
        await self.browser._route_request(self.session,route)
        self.assertEqual(len(self.session['request_errors']),20)
        self.session['manual_until']=time.time()+300
        await self.browser._route_request(self.session,route)
        self.browser.http.request.assert_called_once()

    async def test_approved_read_strips_all_credentials_body_and_response_cookies(self):
        route=self.route();self.approve(route)
        await self.browser._route_request(self.session,route)
        sent=self.browser.http.request.call_args.kwargs
        self.assertEqual(sent['headers'],{'accept':'*/*','origin':'https://site.example.com'})
        self.assertIsNone(sent['body'])
        self.assertNotIn('set-cookie',route.fulfill.call_args.kwargs['headers'])
        self.assertTrue(self.session['has_sensitive_data'])
        other=self.route(url=route.request.url+'?extra=synthetic')
        await self.browser._route_request(self.session,other)
        other.abort.assert_awaited_once();self.assertEqual(self.browser.http.request.call_count,1)

    async def test_send_connection_alone_cannot_send_without_takeover_or_action_approval(self):
        route=self.route('POST','https://api.example.com/login');self.approve(route,True)
        await self.browser._route_request(self.session,route)
        self.browser.http.request.assert_not_called()
        self.session['manual_until']=time.time()+60
        await self.browser._route_request(self.session,route)
        self.assertEqual(self.browser.http.request.call_args.kwargs['body'],b'synthetic-form')
        self.assertIn('authorization',self.browser.http.request.call_args.kwargs['headers'])
        self.session['manual_until']=0;self.session['writes']=True
        await self.browser._route_request(self.session,route)
        self.assertEqual(self.browser.http.request.call_count,2)

    async def test_grants_do_not_allow_cross_site_navigation_or_expired_requests(self):
        route=self.route(navigation=True);self.approve(route)
        await self.browser._route_request(self.session,route)
        self.browser.http.request.assert_not_called()
        route=self.route('POST','https://api.example.com/login');self.approve(route,True)
        self.connections.grants[(route.request.url,'POST')]=time.time()-1
        self.session['writes']=True
        await self.browser._route_request(self.session,route)
        self.browser.http.request.assert_not_called()

    async def test_grant_requires_ownership_current_page_and_public_address(self):
        route=self.route();self.connections.note(route.request.url,'GET','script',self.page.url)
        id=self.connections.view(self.page.url)['pending'][0]['id']
        for cid,page in [('other',self.page.url),('c','https://site.example.com/other')]:
            with self.assertRaises(ServiceError):await self.browser._connection_allow(cid,'s',[id],page)
        self.browser.validate_url.side_effect=ServiceError('仅公网',403)
        with self.assertRaises(ServiceError):await self.browser._connection_allow('c','s',[id],self.page.url)
        self.assertEqual(self.connections.revision,0)
        self.assertFalse(self.connections.permitted(route.request.url,'GET'))

    async def test_connection_changes_invalidate_old_action_before_any_write(self):
        route=self.route('POST','https://api.example.com/send');self.approve(route,True)
        fingerprint=self.connections.fingerprint()
        self.connections.revoke()
        self.browser._fingerprint=AsyncMock(return_value='page-fingerprint')
        plan={'session_id':'s','snapshot_id':'snap','fingerprint':'page-fingerprint',
            'expires_at':time.time()+60,'connection_fingerprint':fingerprint,
            'operations':[{'kind':'click','element_id':'never-executed'}]}
        with self.assertRaisesRegex(ServiceError,'连接授权已变化'):
            await self.browser._execute('c',plan)
        self.browser.http.request.assert_not_called()


import test_tracking as fixtures
class ConnectionApiTests(unittest.TestCase):
    setUp=fixtures.TrackingTests.setUp
    ready=fixtures.TrackingTests.ready

    def test_ui_grant_checks_capability_and_audits_without_url_query_or_payload(self):
        self.ready()
        browser=BrowserService(None)
        self.addCleanup(browser.close)
        page=MagicMock(url='https://site.example.com/login');page.is_closed.return_value=False
        session={'id':'s','conversation_id':self.cid,'page':page,'touched':time.time(),'snapshot_id':'snap',
            'browser':MagicMock(close=AsyncMock()),'lock':None}
        # The dispatch loop owns the asyncio lock, while the test only prepares metadata.
        session.pop('lock')
        browser.sessions['s']=session
        browser.validate_url=MagicMock()
        self.services.platform.browser=browser
        connections=browser._connections(session)
        connections.note('https://cdn.example.com/login.js?secret=synthetic-token','GET','script',page.url)
        path=f'/api/conversations/{self.cid}/browser/s/connections'
        # No browser event loop is used by this metadata-only API fixture.
        def call(method,cid,sid,*args):
            return asyncio.run(getattr(browser,'_'+method)(cid,sid,*args))
        browser.call=call
        view=self.client.get(path)
        self.assertEqual(view.status_code,200);self.assertEqual(view.headers['cache-control'],'no-store')
        id=view.json()['pending'][0]['id']
        response=self.client.post(path,json={'request_ids':[id],'page_url':page.url})
        self.assertEqual(response.status_code,200)
        import json
        self.assertNotIn('synthetic-token',json.dumps(self.services.tool_store.get_audit_logs(self.cid)))
        self.assertEqual(self.client.delete(path).status_code,200)
        self.services.registry.bind_platform(self.agent.id,[])
        self.assertEqual(self.client.get(path).status_code,403)
        self.assertEqual(self.client.post(path,json={'request_ids':[id],'page_url':page.url}).status_code,403)
