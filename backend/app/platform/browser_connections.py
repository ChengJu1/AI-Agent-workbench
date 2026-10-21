"""Human-reviewed, exact-endpoint connections; no automatic request replay."""
import hashlib
import json
import time
from urllib.parse import urlsplit
from uuid import uuid4

from app.errors import ServiceError


class BrowserConnections:
    def __init__(self):
        self.pending = {}
        self.grants = {}
        self.revision = 0

    def note(self, url, method, kind, page_url):
        if method not in ('GET','POST','PUT','PATCH','DELETE') or urlsplit(url).scheme not in ('http','https'):
            return
        now=time.time()
        key=(url,method)
        if self.permitted(url,method):return
        old=self.pending.get(key)
        if old and old['page_url']==page_url and old['expires_at']>now:return
        self.pending[key]={'id':uuid4().hex,'url':url,'method':method,'kind':kind,
            'host':urlsplit(url).netloc,'page_url':page_url,'expires_at':now+600}
        while len(self.pending)>64:self.pending.pop(next(iter(self.pending)))

    def permitted(self,url,method):
        return self.grants.get((url,method),0)>time.time()

    def view(self,page_url):
        now=time.time()
        return {'page_url':page_url,'revision':self.revision,
            'pending':[dict(row) for key,row in self.pending.items() if row['page_url']==page_url and row['expires_at']>now and not self.permitted(*key)],
            'granted':[{'url':url,'method':method,'host':urlsplit(url).netloc,'expires_at':until}
                for (url,method),until in self.grants.items() if until>now]}

    def selected(self,ids,page_url,allow_data):
        rows={row['id']:row for row in self.view(page_url)['pending']}
        if not ids or len(ids)!=len(set(ids)) or any(id not in rows for id in ids):
            raise ServiceError('页面连接清单已变化或已过期，请刷新清单后重新确认。',409)
        selected=[rows[id] for id in ids]
        if any(row['method']!='GET' for row in selected) and not allow_data:
            raise ServiceError('发送资料的连接需要单独勾选确认。',422)
        return selected

    def approve(self,rows):
        for row in rows:
            self.grants[(row['url'],row['method'])]=time.time()+600
        while len(self.grants)>128:self.grants.pop(next(iter(self.grants)))
        self.revision+=1

    def revoke(self):
        self.grants.clear();self.revision+=1

    def fingerprint(self):
        active=sorted((url,method,until) for (url,method),until in self.grants.items() if until>time.time())
        return hashlib.sha256(json.dumps(active).encode()).hexdigest()

    def destinations(self):
        return sorted({f'{urlsplit(url).scheme}://{urlsplit(url).netloc}' for (url,method),until in self.grants.items()
            if method!='GET' and until>time.time()})
