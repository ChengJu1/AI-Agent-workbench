import os
from collections.abc import AsyncIterator

from claude_agent_sdk import ClaudeAgentOptions, StreamEvent, query
from dotenv import load_dotenv

from app.schemas import AgentInfo


load_dotenv()


class ClaudeRuntimeService:
    async def stream_reply(
        self,
        conversation_id: str,
        agent: AgentInfo,
        user_message: str,
        should_resume: bool,
    ) -> AsyncIterator[str]:
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise RuntimeError("缺少 ANTHROPIC_API_KEY，请先在 backend/.env 中配置。")

        session_options = (
            {"resume": conversation_id}
            if should_resume
            else {"session_id": conversation_id}
        )
        options = ClaudeAgentOptions(
            system_prompt=agent.system_prompt,
            tools=[],
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
                yield text
