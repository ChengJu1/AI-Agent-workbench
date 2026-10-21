"""Collect numeric telemetry only; component token counts are not billing totals."""
import json
import os

from time import perf_counter

from claude_agent_sdk import AssistantMessage, ToolResultBlock, ToolUseBlock, UserMessage

from app.services.token_counter import TokenCounter


class RuntimeUsage:
    def __init__(self, system_prompt, model=None):
        self.started = perf_counter()
        self.first_delta = None
        self.tool_ids = set()
        self.result = None
        self.counter = TokenCounter(model if model is not None else os.getenv('ANTHROPIC_MODEL'))
        self.component_tokens = {name: self.counter.count('') for name in
                                 ('system_prompt', 'tool_result', 'history', 'tool_description', 'user_message')}
        self.set_component('system_prompt', system_prompt or '')
        self.component_tokens['history'] = None
        self.history_complete = False
        self.tool_descriptions_complete = True

    def set_component(self, name, text):
        self.component_tokens[name] = self.counter.count(text)

    def add_component(self, name, text):
        count = self.counter.count(text)
        current = self.component_tokens[name]
        self.component_tokens[name] = current + count if current is not None and count is not None else None

    def capture(self, message):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    self.tool_ids.add(block.id)
        if isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    text = block.content if isinstance(block.content, str) else json.dumps(block.content, ensure_ascii=False)
                    self.add_component('tool_result', text)

    def delta(self):
        if self.first_delta is None:
            self.first_delta = (perf_counter() - self.started) * 1000

    def snapshot(self):
        result = self.result
        usage = (result.usage or {}) if result else {}
        def count(name):
            value = usage.get(name)
            return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
        return {
            'runtime': 'claude_sdk',
            'input_tokens': count('input_tokens'), 'output_tokens': count('output_tokens'),
            'cache_read_input_tokens': count('cache_read_input_tokens'),
            'cache_creation_input_tokens': count('cache_creation_input_tokens'),
            # SDK num_turns counts the agent's model turns, including tool rounds.
            'model_calls': result.num_turns if result else None,
            'tool_calls': len(self.tool_ids),
            'first_token_ms': self.first_delta,
            'duration_ms': (perf_counter() - self.started) * 1000,
            'status': 'complete' if result and not result.is_error and result.subtype == 'success' else 'failed',
            'context_estimate': {
                'method': 'local_tokenizer',
                'tokenizer': dict(self.counter.metadata),
                **{name + '_tokens': count for name, count in self.component_tokens.items()},
                'tool_descriptions_complete': self.tool_descriptions_complete,
                'history_available': self.history_complete,
                'coverage': {
                    'system_prompt': 'current_system_prompt_plain_text',
                    'tool_description': 'in_process_mcp_schema_json_only',
                    'history': 'stored_user_and_assistant_texts_counted_separately',
                    'tool_result': 'current_turn_observed_result_text_or_json',
                    'user_message': 'current_user_message_plain_text',
                    'excluded': ['sdk_internal_history', 'chat_template', 'external_tool_schemas', 'images'],
                },
                'limitation': 'History is a local transcript proxy; tool descriptions cover in-process tools only. SDK-managed history and wire schemas may differ. Components are not additive across model calls.',
            },
        }
