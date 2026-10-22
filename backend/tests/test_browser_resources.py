import unittest
from app.platform.browser_resources import PublicResourceCache


class PublicResourceCacheTests(unittest.TestCase):
    def response(self, body=b'public script', mime='text/javascript'):
        return {'status':200,'headers':[('Content-Type',mime),('Set-Cookie','must-not-replay=1')],'body':body}

    def test_exact_previously_observed_resource_can_be_replayed_without_cookies(self):
        cache=PublicResourceCache();url='https://cdn.example.com/app.js?v=public'
        cache.remember(url,'script',self.response())
        self.assertEqual(cache.get(url,'script')['body'],b'public script')
        self.assertEqual(cache.get(url,'script')['headers'],[('Content-Type','text/javascript')])
        self.assertIsNone(cache.get(url+'&private=data','script'))
        self.assertIsNone(cache.get(url.replace('app.js','other.js'),'script'))
        self.assertIsNone(cache.get(url,'fetch'))

    def test_documents_dynamic_api_responses_and_errors_are_not_cached(self):
        cache=PublicResourceCache()
        for kind,mime in [('document','text/html'),('fetch','application/json'),('script','text/html')]:
            cache.remember('https://cdn.example.com/resource',kind,self.response(mime=mime))
        cache.remember('https://cdn.example.com/error.js','script',self.response()|{'status':404})
        self.assertFalse(cache.entries)

    def test_previously_public_static_files_loaded_by_fetch_and_images_are_replayed(self):
        cache=PublicResourceCache()
        for url,kind,mime in [('https://cdn.example.com/logo.svg','fetch','image/svg+xml'),
                              ('https://cdn.example.com/site.json','fetch','application/json'),
                              ('https://cdn.example.com/logo.png','image','image/png')]:
            cache.remember(url,kind,self.response(mime=mime))
            self.assertIsNotNone(cache.get(url,kind))

    def test_no_store_responses_are_never_replayed(self):
        cache=PublicResourceCache()
        cache.remember('https://cdn.example.com/qr.png','image',self.response(mime='image/png'))
        response=self.response(mime='image/png')
        response['headers'].append(('Cache-Control','max-age=0, no-store'))
        cache.remember('https://cdn.example.com/qr.png','image',response)
        self.assertFalse(cache.entries)

    def test_previously_public_html_components_are_cached_but_documents_and_html_apis_are_not(self):
        cache=PublicResourceCache()
        cache.remember('https://cdn.example.com/header.html','fetch',self.response(mime='text/html'))
        self.assertIsNotNone(cache.get('https://cdn.example.com/header.html','fetch'))
        cache.remember('https://cdn.example.com/page.html','document',self.response(mime='text/html'))
        cache.remember('https://cdn.example.com/account','fetch',self.response(mime='text/html'))
        self.assertIsNone(cache.get('https://cdn.example.com/page.html','document'))
        self.assertIsNone(cache.get('https://cdn.example.com/account','fetch'))

    def test_memory_is_bounded_and_cache_is_session_local(self):
        cache=PublicResourceCache(max_bytes=6,max_entries=2)
        for i in range(3):cache.remember(f'https://cdn.example.com/{i}.js','script',self.response(body=b'123'))
        self.assertIsNone(cache.get('https://cdn.example.com/0.js','script'))
        self.assertEqual(cache.bytes,6)
        self.assertFalse(PublicResourceCache().entries)
        cache.remember('https://cdn.example.com/large.js','script',self.response(body=b'1234567'))
        self.assertIsNone(cache.get('https://cdn.example.com/large.js','script'))
