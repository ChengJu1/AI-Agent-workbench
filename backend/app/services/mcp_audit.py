"""Audit actual MCP tool execution, independently of model message classes."""
import anyio


class McpAuditTracker:
    def __init__(self, store, conversation_id, agent_id, allowed_tools, result_observer=None):
        self.store = store
        self.conversation_id = conversation_id
        self.agent_id = agent_id
        self.allowed_tools = set(allowed_tools)
        self.result_observer = result_observer

    async def execute(self, server, action, arguments, invoke):
        if f'mcp__{server}__{action}' not in self.allowed_tools:
            raise PermissionError('当前 Agent 未授权该 MCP 工具。')
        call = {'tool_name': server, 'action': action, 'params': arguments}
        content, error = None, None
        try:
            response = await invoke()
            content = response.get('content', [])
            if response.get('isError') or response.get('is_error'):
                error = 'MCP 工具调用失败'
            return response
        except BaseException as exception:
            error = 'MCP 工具没有返回执行结果' if isinstance(exception, anyio.get_cancelled_exc_class()) else 'MCP 工具调用失败'
            raise
        finally:
            # Even cancellation must leave a failed audit and retain earlier evidence.
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(
                    lambda: self.store.add_audit_log(
                        self.conversation_id, self.agent_id, server, action, arguments,
                        'failed' if error else 'success', result=content if not error else None,
                        error=error, tool_type='mcp',
                    )
                )
                if self.result_observer is not None:
                    self.result_observer(call, content, bool(error))
