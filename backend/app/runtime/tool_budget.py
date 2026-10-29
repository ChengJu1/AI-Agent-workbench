"""Per-turn cap on tool calls: once spent, the model answers from what it has instead of exploring further."""
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage

from app.runtime.tool_activity import current_activity
from app.runtime.turn_state import PREFIX

NOTICE = ('本轮已调用 {used} 次工具，达到单轮上限 {limit} 次，工具已暂停。请只根据已经拿到的结果回答，'
          '说明哪些结论已核实、还缺哪些信息；需要继续时请用户再发一条消息。')
# 被委派的成员没有用户可以回话：由委派它的 Agent 决定是否让它接着做，子会话会保留现在的进度。
MEMBER_NOTICE = ('本次任务已调用 {used} 次工具，达到单轮上限 {limit} 次，工具已暂停。请只根据已经拿到的结果回复：'
                 '先写已核实的结论，再列出还没完成的部分和接下来要查什么。委派你的 Agent 可以让你接着做，你会记得现在的进度。')


class ToolBudgetMiddleware(AgentMiddleware):
    # One instance per turn: the graph is rebuilt for every reply.
    def __init__(self, limit):
        super().__init__()
        self.limit, self.used, self.reported = limit, 0, False

    def _spent(self, request):
        if self.limit is None or self.used < self.limit:
            return request
        from app.tools.team_tools import running_as_member
        if not self.reported and (activity := current_activity()) is not None:
            # 委派方据此知道成员没做完。
            activity.emit({'type': 'tool_limit_reached', 'used': self.used, 'limit': self.limit})
            self.reported = True
        text = MEMBER_NOTICE if running_as_member() else NOTICE
        notice = HumanMessage(PREFIX + text.format(used=self.used, limit=self.limit))
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
