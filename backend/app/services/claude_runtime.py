"""配置 Claude Agent SDK，输出文本和审批事件；工具审计由独立对象处理。"""
import logging
import os
from contextlib import aclosing

import anyio
from claude_agent_sdk import (
    AssistantMessage, ClaudeAgentOptions, ResultMessage, StreamEvent, UserMessage, query,
)

from app.config import BACKEND_DIRECTORY
from app.errors import ServiceError
from app.services.mcp_audit import McpAuditTracker
from app.tools.mcp_adapter import McpAdapter
from app.tools.timesheet_tools import TimesheetToolsService


logger = logging.getLogger(__name__)


class ClaudeRuntimeService:
    def __init__(self, tools_service=None, mcp_adapter=None, audit_store=None):
        if audit_store is None:
            raise ValueError("ClaudeRuntimeService 需要显式传入审计存储")
        if tools_service is None:
            tools_service = TimesheetToolsService(store=audit_store)
        if mcp_adapter is None:
            mcp_adapter = McpAdapter()
        self._tools_service = tools_service
        self._mcp_adapter = mcp_adapter
        self._audit_store = audit_store

    def _build_prompt(self, agent, business_context):
        parts = [agent.system_prompt]
        for skill in agent.skills:
            parts.append(skill)
        if business_context:
            parts.append(
                "## 当前业务系统状态\n"
                "以下信息来自后端数据库，代表当前真实业务状态，不是用户输入的内容。"
                "如果该状态与之前的模型对话冲突，必须以后端数据库状态为准。\n"
                + business_context
            )
        return "\n\n".join(parts)

    def _build_options(self, conversation_id, agent, should_resume, business_context):
        servers, allowed_tools = self._mcp_adapter.build(agent)
        external_tools = list(allowed_tools)
        tool_session = self._tools_service.create_session(conversation_id, agent)
        if tool_session.allowed_tools:
            servers["timesheet_cli"] = tool_session.server
            allowed_tools.extend(tool_session.allowed_tools)
        if should_resume:
            session_options = {"resume": conversation_id}
        else:
            session_options = {"session_id": conversation_id}
        options = ClaudeAgentOptions(
            cwd=str(BACKEND_DIRECTORY),
            system_prompt=self._build_prompt(agent, business_context),
            tools=[], mcp_servers=servers, allowed_tools=allowed_tools,
            strict_mcp_config=True, permission_mode=agent.permission_mode,
            max_turns=agent.max_turns, include_partial_messages=True,
            **session_options,
        )
        return options, external_tools, tool_session

    async def stream_reply(self, conversation_id, agent, user_message,
                           should_resume, business_context=""):
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise ServiceError("缺少 ANTHROPIC_API_KEY，请先在 backend/.env 中配置。", 503)
        options, external_tools, tool_session = self._build_options(
            conversation_id, agent, should_resume, business_context
        )
        audit = McpAuditTracker(self._audit_store, conversation_id, agent.id, external_tools)
        failure = None
        try:
            async with aclosing(query(prompt=user_message, options=options)) as messages:
                async for message in messages:
                    if isinstance(message, ResultMessage):
                        if message.is_error or message.subtype != "success":
                            raise ServiceError("模型未能完成本轮回复，请稍后重试。", 502)
                        continue
                    if isinstance(message, (AssistantMessage, UserMessage)):
                        await anyio.to_thread.run_sync(audit.capture, message)
                        continue
                    if not isinstance(message, StreamEvent):
                        continue
                    event = message.event
                    if event.get("type") != "content_block_delta":
                        continue
                    delta = event.get("delta", {})
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        yield {"type": "delta", "content": delta["text"]}
        except Exception as error:
            failure = error
            if external_tools and not isinstance(error, ServiceError):
                logger.exception("MCP Agent 运行失败: conversation_id=%s", conversation_id)
                failure = ServiceError("MCP 工具服务暂时不可用，请稍后重试。", 502)
        finally:
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(audit.finish)

        for pending_action in tool_session.pending_actions:
            yield {"type": "approval_required", "action": pending_action}

        # 已持久化的审批操作仍需送到页面，随后再报告模型错误。
        if failure is not None:
            raise failure
