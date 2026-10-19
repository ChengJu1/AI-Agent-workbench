"""Conversation-scoped capability dispatcher; no platform access from generated code."""
import json
import time

from app.errors import ServiceError
from app.platform.browser import BrowserService
from app.platform.catalog import CATALOG, TOOL_CAPABILITIES
from app.platform.files import FileService
from app.platform.web import WebService

SERVER_NAME = 'workbench_platform'


class PlatformService:
    def __init__(self, database, registry, conversations, tool_store, web=None, browser=None):
        self.database, self.registry, self.conversations, self.tool_store = database, registry, conversations, tool_store
        self.files = FileService(database)
        self.web = web or WebService()
        self.browser = browser or BrowserService(self.files)

    def require(self, conversation_id, capability):
        agent_id = self.conversations.get_agent_id(conversation_id)
        agent = self.registry.get_agent(agent_id) if agent_id else None
        if agent is None:
            raise ServiceError('会话或 Agent 不存在。', 404)
        if capability not in agent.platform_capabilities:
            raise ServiceError('当前 Agent 未启用该基础能力，请先在基础能力设置中授权。', 403)
        return agent

    def execute(self, conversation_id, name, arguments):
        capability = TOOL_CAPABILITIES.get(name)
        if capability is None:
            raise ServiceError('基础工具不存在。', 404)
        agent = self.require(conversation_id, capability)
        if name == 'list_files':
            return {'files': self.files.list(conversation_id)}
        if name == 'read_file':
            return self.files.read(conversation_id, arguments['file_id'], arguments.get('offset', 0), arguments.get('limit', 12000))
        if name == 'web_search':
            return self.web.search(arguments['query'], arguments.get('limit', 5))
        if name == 'web_read':
            return self.web.read(arguments['url'], arguments.get('offset', 0), arguments.get('limit', 12000))
        if name == 'list_browser_sessions':
            return {'sessions': self.browser.call('list', conversation_id)}
        if name == 'browser_open':
            return self.browser.call('open', conversation_id, arguments['url'])
        if name == 'browser_read':
            return self.browser.call('read', conversation_id, arguments['session_id'])
        if name == 'browser_close':
            return self.browser.call('close', conversation_id, arguments['session_id'])
        if name == 'browser_prepare_actions':
            operations = arguments['operations']
            if any(op.get('kind') == 'upload' for op in operations):
                self.require(conversation_id, 'files')
            plan = self.browser.call('prepare', conversation_id, arguments['session_id'], arguments['snapshot_id'], operations)
            # An identical pending batch returns the same approval instead of creating duplicates.
            for pending in self.tool_store.get_pending_actions(conversation_id):
                if pending['tool_name'] == SERVER_NAME and all(pending['params'].get(key) == plan.get(key) for key in ('session_id', 'snapshot_id', 'fingerprint', 'operations')) and pending['params'].get('expires_at', 0) > time.time():
                    return {'approval_required': True, 'pending_action': pending}
            action_id = self.tool_store.create_pending_action(conversation_id, agent.id, SERVER_NAME, 'browser_actions', plan, tool_type='browser')
            return {'approval_required': True, 'pending_action': self.tool_store.get_pending_action(action_id),
                    'notice': '只生成了待确认清单，没有执行填表、上传或点击。等待用户在网页中确认，不得声称已投递。'}

    def execute_approved(self, action):
        self.require(action['conversation_id'], 'browser')
        if any(op.get('kind') == 'upload' for op in action['params']['operations']):
            self.require(action['conversation_id'], 'files')
        return self.browser.call('execute', action['conversation_id'], action['params'])

    def catalog(self):
        return {'capabilities': CATALOG, 'browser': self.browser.status(),
                'search': {'provider': 'ddgs', 'requires_key': False, 'notice': '公开搜索可能遇到网络、限流或验证限制；不会伪造结果。'}}
