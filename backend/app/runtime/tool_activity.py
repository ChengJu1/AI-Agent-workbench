"""Per-turn, framework-independent tool status events without arguments or results."""
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock


_current = ContextVar('workbench_tool_activity', default=None)


class ToolActivity:
    def __init__(self):
        self._events = []
        self._next = 0
        self._lock = Lock()

    async def execute(self, name, invoke):
        with self._lock:
            self._next += 1
            call_id = f'tool-{self._next}'
            self._events.append({'type': 'tool_started', 'tool_name': name, 'call_id': call_id})
        success = False
        try:
            result = await invoke()
            success = not (result.get('is_error') or result.get('isError'))
            return result
        finally:
            with self._lock:
                self._events.append({'type': 'tool_finished', 'tool_name': name,
                                     'call_id': call_id, 'success': success})

    def drain(self):
        with self._lock:
            events, self._events = self._events, []
        return events

    @contextmanager
    def bind(self):
        token = _current.set(self)
        try:
            yield self
        finally:
            _current.reset(token)


async def record_tool_activity(name, invoke):
    activity = _current.get()
    return await activity.execute(name, invoke) if activity is not None else await invoke()
