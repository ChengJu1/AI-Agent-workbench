"""Conversation-scoped capability dispatcher; no platform access from generated code."""
import time

from app.errors import ServiceError
from app.platform.native_browser import browser_provider
from app.platform.catalog import CATALOG, TOOL_CAPABILITIES
from app.platform.files import FileService
from app.platform.web import WebService
from app.models.tracking import TrackingDefinition, WorkItemSave

SERVER_NAME = 'workbench_platform'


class PlatformService:
    def __init__(self, database, registry, conversations, tool_store, web=None, browser=None):
        self.database, self.registry, self.conversations, self.tool_store = database, registry, conversations, tool_store
        self.files = FileService(database)
        self.web = web or WebService()
        self.browser = browser or browser_provider(self.files)

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
        if capability == 'applications':
            return self.application_actions.dispatch(conversation_id, name, arguments)
        if name == 'save_work_item':
            return self.tracking.items.save(conversation_id, agent.id, WorkItemSave.model_validate(arguments))
        if name == 'list_work_items':
            return {'items': self.tracking.items.list(agent.id)}
        if name == 'read_work_item':
            return self.tracking.items.get(arguments['item_id'], agent.id)
        if name == 'list_records':
            return {'records': self.tracking.store.records(agent.id)}
        if name == 'list_tracking':
            return {'tasks': self.tracking.store.tasks(agent.id)}
        if name == 'read_tracking':
            return self.tracking.store.get(arguments['task_id'], agent.id)
        if name == 'create_tracking':
            return self.tracking.create(conversation_id, TrackingDefinition.model_validate(arguments))
        if name == 'check_file':
            return self.files.check(conversation_id, arguments['file_id'])
        if name == 'update_file':
            plan = self.files.prepare_update(conversation_id, **arguments)
            plan['expires_at'] = time.time() + 300
            for pending in self.tool_store.get_pending_actions(conversation_id):
                if pending['action'] == 'update_file' and all(pending['params'].get(key) == value for key,value in plan.items() if key != 'expires_at') and pending['params'].get('expires_at', 0) > time.time():
                    return {'approval_required': True, 'pending_action': pending}
            action_id = self.tool_store.create_pending_action(conversation_id, agent.id, SERVER_NAME, 'update_file', plan, tool_type='file')
            return {'approval_required': True, 'pending_action': self.tool_store.get_pending_action(action_id), 'notice': '文件尚未更新，请等待用户确认。'}
        if name == 'list_files':
            return {'files': self.files.list(conversation_id)}
        if name == 'read_file':
            return self.files.read(conversation_id, arguments['file_id'], arguments.get('offset', 0), arguments.get('limit', 12000), arguments.get('version'))
        if name == 'web_search':
            return self.web.search(arguments['query'], arguments.get('limit', 5))
        if name == 'web_read':
            return self.web.read(arguments['url'], arguments.get('offset', 0), arguments.get('limit', 12000))
        if name == 'list_browser_sessions':
            return {'sessions': self.browser.call('list', conversation_id)}
        if name == 'browser_open':
            attempt = self.tracking.items.begin_attempt(conversation_id, agent.id, arguments['url']) if 'tracking' in agent.platform_capabilities else None
            try:
                result = self.browser.call('open', conversation_id, arguments['url'])
            except Exception as error:
                self.tracking.items.finish_attempt(attempt, error=str(error) if isinstance(error, ServiceError) else '浏览器读取失败，请核对运行环境。')
                raise
            self.tracking.items.finish_attempt(attempt, result)
            if attempt:
                result = {**result, 'work_item_id':attempt['item_id'], 'work_item_attempt_id':attempt['id']}
            return result
        if name == 'browser_read':
            defaults = {'snapshot_id': None, 'query': None, 'text_offset': 0, 'text_limit': 12000,
                        'element_offset': 0, 'element_limit': 80}
            options = {key: arguments[key] for key, value in defaults.items() if key in arguments and arguments[key] != value}
            if options:
                if self.browser.status().get('provider') != 'native_mcp':
                    raise ServiceError('当前浏览器方案不支持完整快照分页，请使用 native_mcp。', 422)
                if not options.get('snapshot_id') and (options.get('text_offset') or options.get('element_offset')):
                    raise ServiceError('继续翻页需提供上次返回的 snapshot_id。', 422)
                return self.browser.call('read', conversation_id, arguments['session_id'], arguments.get('tab_index'), options)
            if arguments.get('tab_index') is not None:
                if self.browser.status().get('provider') != 'native_mcp':
                    raise ServiceError('当前浏览器方案不支持标签选择。', 422)
                return self.browser.call('read', conversation_id, arguments['session_id'], arguments['tab_index'])
            return self.browser.call('read', conversation_id, arguments['session_id'])
        if name == 'browser_close':
            return self.browser.call('close', conversation_id, arguments['session_id'])
        if name == 'browser_prepare_actions':
            operations = arguments['operations']
            if any(op.get('kind') == 'upload' for op in operations):
                self.require(conversation_id, 'files')
            plan = self.browser.call('prepare', conversation_id, arguments['session_id'], arguments['snapshot_id'], operations)
            if arguments.get('work_item_id'):
                self.require(conversation_id, 'tracking')
                self.tracking.items.validate_link(arguments['work_item_id'], conversation_id, plan['url'])
                plan['work_item_id'] = arguments['work_item_id']
            # An identical pending batch returns the same approval instead of creating duplicates.
            for pending in self.tool_store.get_pending_actions(conversation_id):
                if pending['tool_name'] == SERVER_NAME and all(pending['params'].get(key) == plan.get(key) for key in ('session_id', 'snapshot_id', 'fingerprint', 'operations', 'work_item_id')) and pending['params'].get('expires_at', 0) > time.time():
                    return {'approval_required': True, 'pending_action': pending}
            action_id = self.tool_store.create_pending_action(conversation_id, agent.id, SERVER_NAME, 'browser_actions', plan, tool_type='browser')
            return {'approval_required': True, 'pending_action': self.tool_store.get_pending_action(action_id),
                    'notice': '只生成了待确认清单，没有执行填表、上传或点击。等待用户在网页中确认，不得声称已投递。'}

    def execute_approved(self, action):
        if action['action'] == 'update_file':
            self.require(action['conversation_id'], 'files')
            if time.time() > action['params']['expires_at']:
                raise ServiceError('文件更新确认已过期，请重新生成。', 409)
            return self.files.execute_update(action['conversation_id'], action['params'])
        self.require(action['conversation_id'], 'browser')
        if action['params'].get('work_item_id'):
            self.require(action['conversation_id'], 'tracking')
            self.tracking.items.validate_link(action['params']['work_item_id'], action['conversation_id'], action['params']['url'])
        if any(op.get('kind') == 'upload' for op in action['params']['operations']):
            self.require(action['conversation_id'], 'files')
        return self.browser.call('execute', action['conversation_id'], action['params'])

    def catalog(self):
        return {'capabilities': CATALOG, 'browser': self.browser.status(),
                'search': {'provider': 'ddgs', 'requires_key': False, 'notice': '公开搜索可能遇到网络、限流或验证限制；不会伪造结果。'}}
