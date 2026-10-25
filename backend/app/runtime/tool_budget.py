"""Per-turn cap on tool calls: once spent, the model answers from what it has instead of exploring further."""
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage

from app.runtime.turn_state import PREFIX

NOTICE = ('本轮已调用 {used} 次工具，达到单轮上限 {limit} 次，工具已暂停。请只根据已经拿到的结果回答，'
          '说明哪些结论已核实、还缺哪些信息；需要继续时请用户再发一条消息。')


class ToolBudgetMiddleware(AgentMiddleware):
    # One instance per turn: the graph is rebuilt for every reply.
    def __init__(self, limit):
        super().__init__()
        self.limit, self.used = limit, 0

    def _spent(self, request):
        if self.limit is None or self.used < self.limit:
            return request
        notice = HumanMessage(PREFIX + NOTICE.format(used=self.used, limit=self.limit))
        return request.override(tools=[], messages=[*request.messages, notice])

    def wrap_model_call(self, request, handler):
        return handler(self._spent(request))

    async def awrap_model_call(self, request, handler):
        return await handler(self._spent(request))

    def wrap_tool_call(self, request, handler):
        self.used += 1
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        self.used += 1
        return await handler(request)
