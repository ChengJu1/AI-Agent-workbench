"""A fake Deep Agents model for one turn: make the scripted tool calls, then answer from their real results."""
import json

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessageChunk, message_chunk_to_message
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import Field


def tool_json(message):
    text = message.content[0]['text'] if isinstance(message.content, list) else message.content
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


class ScriptedTurn(FakeListChatModel):
    calls: list = Field(default_factory=list)       # [(tool name, arguments)], made in order each turn
    reply: object = '合成回答'                      # text, or a function of this turn's parsed tool results
    fail_after_tools: bool = False
    seen: list = Field(default_factory=list)        # every request sent to the model
    results: list = Field(default_factory=list)     # parsed tool results of the latest turn

    def bind_tools(self, tools, **kwargs):
        return self

    async def _astream(self, messages, **kwargs):
        self.seen.append(messages)
        start = max(index for index, message in enumerate(messages) if message.type == 'human')
        done = [message for message in messages[start:] if message.type == 'tool']
        if len(done) < len(self.calls):
            name, arguments = self.calls[len(done)]
            yield ChatGenerationChunk(message=AIMessageChunk(content='', tool_call_chunks=[{
                'name': name, 'args': json.dumps(arguments), 'id': f'call-{len(self.seen)}', 'index': 0}],
                chunk_position='last'))
            return
        self.results = [tool_json(message) for message in done]
        if self.fail_after_tools:
            raise RuntimeError('private-model-details')
        text = self.reply(self.results) if callable(self.reply) else self.reply
        yield ChatGenerationChunk(message=AIMessageChunk(content=text, chunk_position='last'))

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        # Non-streaming callers (a plain LangChain agent) get the same scripted step.
        chunk = None
        async for part in self._astream(messages, **kwargs):
            chunk = part if chunk is None else chunk + part
        return ChatResult(generations=[ChatGeneration(message=message_chunk_to_message(chunk.message))])
