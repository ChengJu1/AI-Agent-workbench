# 负责调用 Claude Agent SDK，并把模型文本和审批事件流式返回。
# Runtime 还会把当前 Agent 的 Prompt、Skill 和工具传给模型。
import os
from collections.abc import AsyncIterator

from claude_agent_sdk import ClaudeAgentOptions, StreamEvent, query
from dotenv import load_dotenv

from app.agent_manifest import LoadedAgent
from app.services.timesheet_tools import TimesheetToolsService


load_dotenv()


class ClaudeRuntimeService:
    def __init__(self, tools_service=None):
        if tools_service is None:
            tools_service = TimesheetToolsService()

        self._tools_service = tools_service

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
        tool_session = self._tools_service.create_session(
            conversation_id,
            agent,
        )

        options = ClaudeAgentOptions(
            system_prompt=system_prompt,
            tools=[],
            mcp_servers={
                "timesheet_cli": tool_session.server
            },
            allowed_tools=tool_session.allowed_tools,
            strict_mcp_config=True,
            permission_mode=agent.permission_mode,
            max_turns=agent.max_turns,
            include_partial_messages=True,
            **session_options,
        )

        async for message in query(prompt=user_message, options=options):
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

        for pending_action in tool_session.pending_actions:
            yield {
                "type": "approval_required",
                "action": pending_action,
            }
