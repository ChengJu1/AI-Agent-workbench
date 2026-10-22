"""Deterministic observation adapters; no model, page writes or automatic resubmission."""
import asyncio
import logging
from urllib.parse import urlsplit
from app.errors import ServiceError
from app.models.tracking import TrackingDefinition
from app.storage.tracking_store import TrackingStore
from app.storage.work_item_store import WorkItemStore

logger = logging.getLogger(__name__)


class TrackingService:
    def __init__(self, platform):
        self.platform = platform
        self.store = TrackingStore(platform.database)
        self.items = WorkItemStore(platform.database)
        self.worker = None
        self.stopping = False
        self.wake = None

    def validate(self, conversation_id, definition):
        self.platform.require(conversation_id, 'tracking')
        self.platform.require(conversation_id, 'web' if definition.mode == 'web' else 'browser')
        parsed = urlsplit(definition.url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
            raise ServiceError('查询入口必须是有效网页地址，不能包含账号密码。', 422)
        if definition.mode == 'web' and definition.selector:
            raise ServiceError('精确元素选择仅用于浏览器查询，公开正文请用唯一对象标识。', 422)
        if definition.record_id:
            record = self.store.record(definition.record_id)
            if record['conversation_id'] != conversation_id:
                raise ServiceError('执行记录不属于当前会话。', 403)
        if definition.mode == 'browser':
            sessions = self.platform.browser.call('list', conversation_id)
            if not any(session['id'] == definition.session_id for session in sessions):
                raise ServiceError('请先在当前会话打开查询页面并完成登录，再关联浏览器。', 409)

    def create(self, conversation_id, definition):
        self.validate(conversation_id, definition)
        agent = self.platform.require(conversation_id, 'tracking')
        return self.store.create(conversation_id, agent.id, definition)

    def check(self, task_id=None):
        task = self.store.claim(task_id)
        if task is None:
            return None
        evidence = {}
        try:
            definition = TrackingDefinition.model_validate(task['definition'])
            self.platform.require(task['conversation_id'], 'tracking')
            self.platform.require(task['conversation_id'], 'web' if definition.mode == 'web' else 'browser')
            if definition.mode == 'web':
                source = self.platform.web.read(definition.url, 0, 20000)
                text = source.get('text', '')
            else:
                source = self.platform.browser.call('observe', task['conversation_id'], definition.session_id, definition.url, definition.selector)
                text = source['text']
            evidence = {'url': source.get('url', definition.url), 'title': source.get('title', '')[:500]}
            # A unique record identifier avoids treating another row's status as this object's.
            if text.count(definition.anchor) != 1:
                raise ServiceError('未找到唯一的对象标识，可能登录失效、页面结构变化或对象不在当前页。请人工核对查询入口。', 409)
            start = text.index(definition.anchor)
            excerpt = text[max(0,start-200):start+len(definition.anchor)+800]
            evidence['excerpt'] = excerpt
            matches = [rule for rule in definition.rules if any(keyword in excerpt for keyword in rule.keywords)]
            if len(matches) != 1:
                raise ServiceError('未匹配到唯一状态，保留原状态；请调整状态关键词或缩小页面元素范围。', 422)
            match = matches[0]
            self.store.finish(task, match.status, 'matched', evidence, terminal=match.terminal)
        except ServiceError as error:
            self.store.finish(task, '', 'blocked' if error.status_code in (403,404,409,410) else 'error', evidence, str(error), blocked=error.status_code in (403,404,409,410))
        except Exception:
            logger.warning('Tracking check failed: id=%s', task['id'])
            self.store.finish(task, '', 'error', evidence, '检查暂时失败，已保留原状态；不会重新执行原操作。')
        return self.store.get(task['id'])

    async def start(self):
        if self.worker is not None:
            return
        self.stopping = False
        self.wake = asyncio.Event()
        self.worker = asyncio.create_task(self._run())

    async def _run(self):
        while not self.stopping:
            try:
                await asyncio.to_thread(self.check)
            except Exception:
                logger.warning('Tracking scheduler could not acquire work')
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=5)
            except TimeoutError:
                pass

    async def close(self):
        self.stopping = True
        if self.worker:
            self.wake.set()
            await self.worker
            self.worker = None
