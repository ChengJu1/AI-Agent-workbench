# 负责调用 Claude Agent SDK，并把模型文本和审批事件流式返回。
# Runtime 还会把当前 Agent 的 Prompt、Skill 和工具传给模型。
import logging
import os
from collections.abc import AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    StreamEvent,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
    query,
)
from dotenv import load_dotenv

from app.agent_manifest import LoadedAgent
from app.services.timesheet_tools import TimesheetToolsService
from app.services.mcp_adapter import McpAdapter
from app.services.tool_store import ToolStore

load_dotenv()

logger = logging.getLogger(__name__)


class ClaudeRuntimeService:
    def __init__(self, tools_service=None, mcp_adapter=None, audit_store=None):
        if tools_service is None:
            tools_service = TimesheetToolsService()
        if mcp_adapter is None:
            mcp_adapter = McpAdapter()
        if audit_store is None:
            audit_store = ToolStore()

        self._tools_service = tools_service
        self._mcp_adapter = mcp_adapter
        self._audit_store = audit_store

    async def stream_reply(
        self,
        conversation_id: str,
        agent: LoadedAgent,
        user_message: str,
        should_resume: bool,
    ) -> AsyncIterator[dict]:
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise RuntimeError("缺少 ANTHROPIC_API_KEY，请先在 backend/.env 中配置。")

        if should_resume:
            session_options = {"resume": conversation_id}
        else:
            session_options = {"session_id": conversation_id}

        prompt_parts = [agent.system_prompt]

        for skill in agent.skills:
            prompt_parts.append(skill)

        system_prompt = "\n\n".join(prompt_parts)
        mcp_servers, allowed_tools = self._mcp_adapter.build(agent)

        mcp_allowed_tools = []
        for i in allowed_tools:
            mcp_allowed_tools.append(i)

        tool_session = self._tools_service.create_session(
            conversation_id,
            agent,
        )

        if tool_session.allowed_tools:
            mcp_servers["timesheet_cli"] = tool_session.server

            for allowed_tool in tool_session.allowed_tools:
                allowed_tools.append(allowed_tool)

        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            tools=[],
            mcp_servers=mcp_servers,
            allowed_tools=allowed_tools,
            strict_mcp_config=True,
            permission_mode=agent.permission_mode,
            max_turns=agent.max_turns,
            include_partial_messages=True,
            **session_options,
        )

        pending_mcp_calls = {}

        try:
            async for message in query(prompt=user_message, options=options):
                if isinstance(message, AssistantMessage):
                    for content_block in message.content:
                        if not isinstance(content_block, ToolUseBlock):
                            continue

                        if content_block.name not in mcp_allowed_tools:
                            continue

                        tool_name_parts = content_block.name.split("__", 2)

                        if len(tool_name_parts) != 3:
                            continue

                        if tool_name_parts[0] != "mcp":
                            continue

                        pending_mcp_calls[content_block.id] = {
                            "tool_name": tool_name_parts[1],
                            "action": tool_name_parts[2],
                            "params": content_block.input,
                        }

                    continue

                if isinstance(message, UserMessage):
                    if not isinstance(message.content, list):
                        continue

                    for content_block in message.content:
                        if not isinstance(content_block, ToolResultBlock):
                            continue

                        pending_mcp_call = pending_mcp_calls.get(
                            content_block.tool_use_id
                        )

                        if pending_mcp_call is None:
                            continue

                        if content_block.is_error:
                            self._audit_store.add_audit_log(
                                conversation_id,
                                agent.id,
                                pending_mcp_call["tool_name"],
                                pending_mcp_call["action"],
                                pending_mcp_call["params"],
                                "failed",
                                error="MCP 工具调用失败",
                                tool_type="mcp",
                            )
                        else:
                            self._audit_store.add_audit_log(
                                conversation_id,
                                agent.id,
                                pending_mcp_call["tool_name"],
                                pending_mcp_call["action"],
                                pending_mcp_call["params"],
                                "success",
                                result=content_block.content,
                                tool_type="mcp",
                            )

                        del pending_mcp_calls[
                            content_block.tool_use_id
                        ]

                    continue

                if not isinstance(message, StreamEvent):
                    continue

                event = message.event
                if event.get("type") != "content_block_delta":
                    continue

                delta = event.get("delta", {})
                if delta.get("type") != "text_delta":
                    continue

                text = delta.get("text", "")
                if text:
                    yield {
                        "type": "delta",
                        "content": text,
                    }
        except Exception as error:
            if mcp_allowed_tools:
                logger.exception(
                    "MCP Agent 运行失败: conversation_id=%s, agent_id=%s",
                    conversation_id,
                    agent.id,
                )
                raise RuntimeError(
                    "制度查询服务暂时不可用，请稍后重试。"
                ) from error

            raise
        finally:
            for pending_mcp_call in pending_mcp_calls.values():
                try:
                    self._audit_store.add_audit_log(
                        conversation_id,
                        agent.id,
                        pending_mcp_call["tool_name"],
                        pending_mcp_call["action"],
                        pending_mcp_call["params"],
                        "failed",
                        error="MCP 工具没有返回执行结果",
                        tool_type="mcp",
                    )
                except Exception:
                    logger.exception(
                        "MCP 未完成调用的审计日志写入失败: "
                        "conversation_id=%s, agent_id=%s",
                        conversation_id,
                        agent.id,
                    )

            pending_mcp_calls.clear()

        for pending_action in tool_session.pending_actions:
            yield {
                "type": "approval_required",
                "action": pending_action,
            }
