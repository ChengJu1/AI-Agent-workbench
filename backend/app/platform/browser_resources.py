"""Replay previously fetched public dependencies without new cross-site traffic."""
from collections import OrderedDict
from urllib.parse import urlsplit
from pathlib import PurePosixPath


class PublicResourceCache:
    def __init__(self, max_bytes=16_000_000, max_entries=128):
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self.bytes = 0
        self.entries = OrderedDict()
        self.observed = OrderedDict()

    def remember(self, url, kind, response):
        headers = response['headers']
        content_type = next((v.lower().split(';')[0].strip() for k,v in headers if k.lower() == 'content-type'), '')
        no_store = any(k.lower() == 'cache-control' and 'no-store' in v.lower() for k,v in headers)
        suffix=PurePosixPath(urlsplit(url).path).suffix.lower()
        self.observed[(url,kind)]={'mime':content_type,'extension':suffix if len(suffix)<=6 else '',
            'cache_policy':next((v for k,v in headers if k.lower() == 'cache-control'),'')[:150]}
        while len(self.observed)>self.max_entries:self.observed.popitem(last=False)
        # Some sites fetch SVG/CSS/config files through fetch(), then render them.
        # A MIME + static file check matters more than the browser's resource label.
        static_type = ('javascript' in content_type or 'ecmascript' in content_type or
                       content_type == 'text/css' or content_type.startswith(('font/','image/')) or
                       (kind == 'font' and content_type in ('application/font-woff','application/vnd.ms-fontobject','application/octet-stream')) or
                       (content_type == 'application/json' and urlsplit(url).path.lower().endswith('.json')) or
                       (kind in ('fetch','xhr') and content_type == 'text/html' and urlsplit(url).path.lower().endswith(('.html','.htm'))))
        supported = kind in ('script','stylesheet','font','image','fetch','xhr') and static_type
        body = response['body']
        key = (url, kind)
        if response['status'] != 200 or not supported or no_store or len(body) > self.max_bytes:
            old = self.entries.pop(key, None)
            if old:self.bytes -= len(old['body'])
            return
        previous = self.entries.pop(key, None)
        if previous:
            self.bytes -= len(previous['body'])
        # Response cookies must never be replayed. URLs (including query strings)
        # match exactly: newly generated data-bearing URLs cannot reuse this entry.
        self.entries[key] = {'status':200, 'body':body,
            'headers':[(k,v) for k,v in headers if k.lower() != 'set-cookie']}
        self.bytes += len(body)
        while self.bytes > self.max_bytes or len(self.entries) > self.max_entries:
            _, old = self.entries.popitem(last=False)
            self.bytes -= len(old['body'])

    def get(self, url, kind):
        return self.entries.get((url, kind))

    def describe(self,url,kind):
        return self.observed.get((url,kind),{})
