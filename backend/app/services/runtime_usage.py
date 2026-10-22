"""Collect numeric telemetry only; component token counts are not billing totals."""
import json
import os
import math

from time import perf_counter

from claude_agent_sdk import AssistantMessage, ToolResultBlock, ToolUseBlock, UserMessage, SystemMessage

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
        self.compact_events = []
        self._compact_ids = set()
        self._compact_starts = []
        self.compact_attempts = 0

    async def pre_compact(self, input, tool_use_id=None, context=None):
        if isinstance(input, dict) and input.get('hook_event_name') == 'PreCompact':
            self.compact_attempts += 1
            self._compact_starts.append(perf_counter())
        return {}

    def compaction_metrics(self):
        return {'compactions_started': self.compact_attempts, 'compactions_completed': len(self.compact_events),
                'compactions_unfinished': len(self._compact_starts), 'compaction_events': list(self.compact_events),
                'summary_model_calls': None if self.compact_attempts or self.compact_events else 0}

    def set_component(self, name, text):
        self.component_tokens[name] = self.counter.count(text)

    def add_component(self, name, text):
        count = self.counter.count(text)
        current = self.component_tokens[name]
        self.component_tokens[name] = current + count if current is not None and count is not None else None

    def capture(self, message):
        if isinstance(message, SystemMessage) and message.subtype == 'compact_boundary':
            data = message.data
            identifier = data.get('uuid')
            if isinstance(identifier, str) and identifier in self._compact_ids:
                return
            if isinstance(identifier, str):
                self._compact_ids.add(identifier)
            metadata = data.get('compact_metadata', data.get('compactMetadata', {}))
            if not isinstance(metadata, dict):
                metadata = {}
            def numeric(snake, camel):
                value = metadata.get(snake, metadata.get(camel))
                valid_type = type(value) is int if snake.endswith('_tokens') else type(value) in (int, float)
                return value if valid_type and value >= 0 and math.isfinite(value) else None
            duration = numeric('duration_ms', 'durationMs')
            source = 'reported' if duration is not None else None
            if self._compact_starts:
                started = self._compact_starts.pop(0)
                if duration is None:
                    duration, source = (perf_counter() - started) * 1000, 'hook_to_boundary'
            self.compact_events.append({'trigger': metadata.get('trigger') if metadata.get('trigger') in ('auto', 'manual') else 'unknown',
                'pre_tokens': numeric('pre_tokens', 'preTokens'), 'post_tokens': numeric('post_tokens', 'postTokens'),
                'duration_ms': duration, 'duration_source': source})
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
