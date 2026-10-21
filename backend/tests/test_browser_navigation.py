import unittest
from unittest.mock import AsyncMock, MagicMock
from playwright.async_api import TimeoutError as NavigationTimeout
from app.platform.browser import BrowserService, browser_response_headers
from app.errors import ServiceError


class BrowserResponseHeaderTests(unittest.TestCase):
    def test_repeated_vary_is_a_comma_list_not_an_invalid_newline(self):
        result = browser_response_headers([('Vary','Accept-Encoding'),('Vary','Accept-Encoding')])
        value = next(value for key, value in result.items() if key.lower() == 'vary')
        self.assertEqual(value, 'Accept-Encoding, Accept-Encoding')
        self.assertNotIn('\n', value)

    def test_header_names_are_case_insensitive_and_cookies_remain_separate(self):
        pairs = [('Vary','Accept-Encoding'),('vary','Origin'),('Set-Cookie','a=1; Path=/'),('set-cookie','b=2; Expires=Wed, 21 Oct 2037 07:28:00 GMT'),('Content-Length','99'),('Connection','keep-alive'),('Transfer-Encoding','chunked')]
        result = browser_response_headers(pairs)
        self.assertEqual(result['vary'], 'Accept-Encoding, Origin')
        self.assertEqual(result['set-cookie'], 'a=1; Path=/\nb=2; Expires=Wed, 21 Oct 2037 07:28:00 GMT')
        self.assertEqual(set(result), {'vary','set-cookie'})


class BrowserNavigationTests(unittest.IsolatedAsyncioTestCase):
    def make_browser(self, result):
        browser = BrowserService(None)
        page = MagicMock()
        page.goto = AsyncMock(side_effect=NavigationTimeout('synthetic timeout'))
        page.wait_for_function = AsyncMock(side_effect=NavigationTimeout('synthetic hydration timeout'))
        browser.sessions['test'] = {'page':page,'http_status':200}
        browser._read = AsyncMock(return_value=result)
        browser._close = AsyncMock()
        return browser

    async def test_keep_real_visible_content_after_resource_timeout(self):
        browser = self.make_browser({'text':'合成页面已可见','elements':[]})
        result = await browser._navigate_and_read('c','test','https://example.com')
        self.assertIn('仅返回当前实际可见内容', result['warning'])
        self.assertEqual(result['http_status'], 200)
        browser._close.assert_not_awaited()

    async def test_empty_timeout_is_explicit_and_closes_browser(self):
        browser = self.make_browser({'text':'  ','elements':[]})
        browser.sessions['test']['http_status'] = None
        with self.assertRaises(ServiceError) as result:
            await browser._navigate_and_read('c','test','https://example.com')
        self.assertEqual(result.exception.status_code, 504)
        browser._close.assert_awaited_once()

    async def test_responded_but_empty_page_stays_available_for_read_or_handoff(self):
        browser = self.make_browser({'text':'','elements':[]})
        result = await browser._navigate_and_read('c','test','https://example.com')
        self.assertIn('未取得可见内容',result['warning'])
        self.assertEqual(result['http_status'],200)
        browser._close.assert_not_awaited()

    async def test_normal_response_has_no_timeout_warning(self):
        browser = self.make_browser({'text':'正常页面','elements':[]})
        browser.sessions['test']['page'].goto.side_effect = None
        result = await browser._navigate_and_read('c','test','https://example.com')
        self.assertNotIn('warning', result)
        self.assertEqual(result['http_status'], 200)

    async def test_initial_empty_spa_snapshot_waits_for_actual_visible_content(self):
        browser = self.make_browser({'text':'','elements':[]})
        browser.sessions['test']['page'].goto.side_effect = None
        browser.sessions['test']['page'].wait_for_function.side_effect = None
        browser._read.side_effect = [{'text':'','elements':[]},{'text':'合成动态正文','elements':[]}]
        result = await browser._navigate_and_read('c','test','https://example.com')
        self.assertEqual(result['text'],'合成动态正文')
        browser.sessions['test']['page'].wait_for_function.assert_awaited_once()
