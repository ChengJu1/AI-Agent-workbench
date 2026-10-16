"""确保响应未开始或网络发送失败时，也会关闭流并释放会话。"""
from fastapi.responses import StreamingResponse


class ManagedStreamingResponse(StreamingResponse):
    def __init__(self, content, on_close, **kwargs):
        super().__init__(content, **kwargs)
        self._on_close = on_close

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._on_close()

    async def stream_response(self, send):
        try:
            await super().stream_response(send)
        finally:
            # ASGI 2.3 会在子任务发送数据，SDK 的取消作用域必须在原任务关闭。
            await self.body_iterator.aclose()
