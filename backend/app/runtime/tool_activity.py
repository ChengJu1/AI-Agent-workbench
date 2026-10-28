"""Per-turn, framework-independent tool status events without arguments or results."""
import asyncio
from contextlib import aclosing, contextmanager
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

    def emit(self, event):
        """推送一条自定义状态事件，例如委派开始和结束。"""
        with self._lock:
            self._events.append(event)

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


def current_activity():
    return _current.get()


async def record_tool_activity(name, invoke):
    activity = _current.get()
    return await activity.execute(name, invoke) if activity is not None else await invoke()


async def with_idle_ticks(stream, interval):
    """转发 stream 的内容；空闲每满 interval 秒插入一个 None，让调用方在工具运行期间也能推送状态。

    stream 始终在同一个任务里迭代，其中设置的上下文变量不会跨任务失效。
    """
    queue, end = asyncio.Queue(), object()

    async def pump():
        try:
            async with aclosing(stream) as items:
                async for item in items:
                    await queue.put((item, None))
            await queue.put((end, None))
        except Exception as error:
            await queue.put((end, error))

    producer = asyncio.create_task(pump())
    try:
        while True:
            try:
                item, error = await asyncio.wait_for(queue.get(), interval)
            except TimeoutError:
                yield None
                continue
            if error is not None:
                raise error
            if item is end:
                return
            yield item
    finally:
        producer.cancel()
        await asyncio.gather(producer, return_exceptions=True)
