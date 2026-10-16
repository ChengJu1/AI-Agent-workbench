"""按工具调用 ID 关联 MCP 请求与结果，记录成功、失败和未完成调用。"""
import logging

from claude_agent_sdk import AssistantMessage, ToolResultBlock, ToolUseBlock, UserMessage


logger = logging.getLogger(__name__)


class McpAuditTracker:
    def __init__(self, store, conversation_id, agent_id, allowed_tools):
        self.store = store
        self.conversation_id = conversation_id
        self.agent_id = agent_id
        self.allowed_tools = set(allowed_tools)
        self.pending = {}

    def capture(self, message):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if not isinstance(block, ToolUseBlock) or block.name not in self.allowed_tools:
                    continue
                parts = block.name.split("__", 2)
                if len(parts) == 3 and parts[0] == "mcp":
                    self.pending[block.id] = {
                        "tool_name": parts[1], "action": parts[2], "params": block.input,
                    }
        elif isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if not isinstance(block, ToolResultBlock):
                    continue
                call = self.pending.get(block.tool_use_id)
                if call is None:
                    continue
                if block.is_error:
                    self._write(call, "failed", error="MCP 工具调用失败")
                else:
                    self._write(call, "success", result=block.content)
                del self.pending[block.tool_use_id]

    def finish(self):
        for call in self.pending.values():
            try:
                self._write(call, "failed", error="MCP 工具没有返回执行结果")
            except Exception:
                logger.exception("MCP 审计保存失败: conversation_id=%s", self.conversation_id)
        self.pending.clear()

    def _write(self, call, status, result=None, error=None):
        self.store.add_audit_log(
            self.conversation_id, self.agent_id, call["tool_name"], call["action"],
            call["params"], status, result=result, error=error, tool_type="mcp",
        )
