"""Tool status must reach the client while a slow tool is still running."""
import asyncio
from contextvars import ContextVar
import unittest

from app.runtime.tool_activity import ToolActivity, with_idle_ticks


class IdleTickTests(unittest.TestCase):
    def test_ticks_while_quiet_and_keeps_items_in_order(self):
        async def stream():
            yield 'first'
            await asyncio.sleep(0.12)
            yield 'second'

        async def run():
            return [item async for item in with_idle_ticks(stream(), 0.03)]
        items = asyncio.run(run())
        self.assertEqual([item for item in items if item is not None], ['first', 'second'])
        self.assertGreaterEqual(items.count(None), 2)

    def test_started_event_is_visible_before_the_tool_finishes(self):
        activity, release = ToolActivity(), None

        async def tool():
            await release.wait()
            return {'content': []}

        async def stream():
            yield 'model'
            yield await activity.execute('mcp__mail__search', tool)

        async def run():
            nonlocal release
            release, seen = asyncio.Event(), []
            async for item in with_idle_ticks(stream(), 0.02):
                seen.extend(event['type'] for event in activity.drain())
                if item is None and 'tool_started' in seen:
                    release.set()
            seen.extend(event['type'] for event in activity.drain())
            return seen
        self.assertEqual(asyncio.run(run()), ['tool_started', 'tool_finished'])

    def test_stream_errors_propagate_and_context_set_inside_stream_survives_yields(self):
        marker = ContextVar('marker', default=None)

        async def stream():
            token = marker.set('inside')
            yield 1
            yield marker.get()
            marker.reset(token)
            raise RuntimeError('graph failed')

        async def run():
            items = []
            with self.assertRaisesRegex(RuntimeError, 'graph failed'):
                async for item in with_idle_ticks(stream(), 1):
                    items.append(item)
            return items
        self.assertEqual(asyncio.run(run()), [1, 'inside'])

    def test_closing_early_cancels_the_stream(self):
        closed = asyncio.Event()

        async def stream():
            try:
                yield 1
                await asyncio.Event().wait()
            finally:
                closed.set()

        async def run():
            ticks = with_idle_ticks(stream(), 1)
            self.assertEqual(await anext(ticks), 1)
            await ticks.aclose()
            self.assertTrue(closed.is_set())
        asyncio.run(run())


if __name__ == '__main__':
    unittest.main()
