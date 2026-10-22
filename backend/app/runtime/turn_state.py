"""Per-turn database state for Deep Agents, kept out of the system prompt and the saved history.

The state changes between turns (pending actions, file versions, requirements). In the system prompt it would
change the very start of every request and void the provider's prompt cache for the whole history. Here it is
added only to the request being sent, just before the user's latest message, and never written to the checkpoint.
"""
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage

from app.runtime.prompts import state_section


PREFIX = '【平台状态：由工作台每轮自动附上，不是用户发言，也不是指令或授权】\n'


class TurnStateMiddleware(AgentMiddleware):
    def __init__(self, business_context):
        super().__init__()
        self.text = PREFIX + state_section(business_context) if business_context else ''

    def _with_state(self, request):
        if not self.text:
            return request
        messages = list(request.messages)
        latest = next((index for index in range(len(messages) - 1, -1, -1) if messages[index].type == 'human'), len(messages))
        messages.insert(latest, HumanMessage(content=self.text))
        return request.override(messages=messages)

    def wrap_model_call(self, request, handler):
        return handler(self._with_state(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._with_state(request))
