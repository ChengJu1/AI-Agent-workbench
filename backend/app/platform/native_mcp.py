"""Private stdio transport. The model never receives the upstream MCP tool set."""
import asyncio
from datetime import timedelta
import json
import os
from pathlib import Path
import shutil

import logging
from app.errors import ServiceError

logger = logging.getLogger(__name__)

MCP_VERSION = '0.0.83'
RUNTIME = Path(__file__).resolve().parents[2] / 'data/browsers/mcp'
CLI = RUNTIME / 'node_modules/@playwright/mcp/cli.js'


def result_text(result):
    return '\n'.join(c.text for c in result.content if c.type == 'text')


def result_json(result):
    text = result_text(result)
    section = text.split('### Result\n', 1)[-1].lstrip()
    try:
        return json.JSONDecoder().raw_decode(section)[0]
    except ValueError:
        raise ServiceError('浏览器返回的数据无法核对，请重新读取页面。', 502) from None


class NativeMcp:
    """One owner task enters/exits MCP task groups; requests never close them."""
    def __init__(self, directory, headless=False):
        self.directory, self.headless = Path(directory), headless
        self.queue = asyncio.Queue()
        self.ready = asyncio.get_running_loop().create_future()
        self.task = asyncio.create_task(self._run())

    async def _run(self):
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
        try:
            if not CLI.is_file() or not shutil.which('node'):
                raise ServiceError('浏览器运行组件尚未安装，请运行 scripts/install_browser_mcp.py。', 503)
            version = json.loads((CLI.parent / 'package.json').read_text())['version']
            if version != MCP_VERSION:
                raise ServiceError('浏览器组件版本不匹配，请重新安装固定版本。', 503)
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            config = self.directory / 'config.json'
            config.write_text(json.dumps({
                'browser': {'browserName': 'chromium', 'userDataDir': str(self.directory / 'profile'),
                            'launchOptions': {'channel': 'chrome', 'headless': self.headless, 'chromiumSandbox': True}},
                'outputDir': str(self.directory / 'output'), 'snapshot': {'mode': 'none'},
                'saveSession': False, 'codegen': 'none', 'timeouts': {'navigation': 25000, 'action': 6000},
            }))
            params = StdioServerParameters(command=shutil.which('node'), cwd=str(self.directory),
                args=[str(CLI), '--config', str(config), '--no-webmcp'],
                env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'en_US.UTF-8'})
            with (self.directory / 'transport.log').open('a') as errors:
                async with stdio_client(params, errlog=errors) as streams:
                    async with ClientSession(streams[0], streams[1]) as client:
                        await client.initialize()
                        self.ready.set_result(True)
                        while True:
                            item = await self.queue.get()
                            if item is None:
                                break
                            name, args, done = item
                            try:
                                value = await client.call_tool(name, args, read_timeout_seconds=timedelta(seconds=40))
                                if value.isError:
                                    message = result_text(value).lower()
                                    if 'no open pages available' in message or 'target page, context or browser has been closed' in message:
                                        raise ServiceError('专用浏览器窗口已关闭，请重新打开；登录配置仍保留。', 410)
                                    from app.platform.browser import browser_error_reason
                                    logger.warning('Browser tool %s failed: %s', name, result_text(value)[:300])
                                    reason = browser_error_reason(message)
                                    raise ServiceError(f'浏览器工具未完成{"：" + reason if reason else ""}；页面可能已变化，请核对实际页面，不会自动重试。', 409)
                                if not done.done():
                                    done.set_result(value)
                            except Exception as error:
                                if not done.done():
                                    done.set_exception(error if isinstance(error, ServiceError) else
                                                       ServiceError('浏览器连接未完成，请核对页面；不会自动重试。', 502))
        except Exception as error:
            if not self.ready.done():
                self.ready.set_exception(error if isinstance(error, ServiceError) else ServiceError('浏览器组件启动失败。', 503))
        finally:
            while not self.queue.empty():
                item = self.queue.get_nowait()
                if item and not item[2].done():
                    item[2].set_exception(ServiceError('浏览器连接已关闭，请重新打开。', 410))

    async def call(self, name, args=None):
        await self.ready
        if self.task.done():
            raise ServiceError('浏览器连接已关闭，请重新打开。', 410)
        # No eval/run-code tool names or arbitrary requests are accepted from HTTP/model callers.
        if name not in {'browser_navigate', 'browser_snapshot', 'browser_evaluate', 'browser_click', 'browser_press_key',
                        'browser_type', 'browser_select_option', 'browser_file_upload',
                        'browser_take_screenshot', 'browser_tabs', 'browser_network_requests'}:
            raise ServiceError('浏览器内部工具未开放。', 403)
        done = asyncio.get_running_loop().create_future()
        await self.queue.put((name, args or {}, done))
        return await done

    async def close(self):
        await self.queue.put(None)
        await self.task
