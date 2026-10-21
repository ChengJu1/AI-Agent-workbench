"""Finite commands for the attended experiment, not a general MCP proxy."""
from urllib.parse import urlsplit
import re

MCP_VERSION = '0.0.83'
BASE = 'http://127.0.0.1:8088'
JOB = 'https://szkingdom.zhiye.com/campus/detail?jobAdId=da7cb700-c052-476e-bbde-6e36b896c04c'
LOGIN = 'https://szkingdom.zhiye.com/login?goto=campus%2Fdetail%3FjobAdId%3Dda7cb700-c052-476e-bbde-6e36b896c04c'
COMMANDS = {
    'open-job': ('browser_navigate', {'url': JOB}),
    'open-login': ('browser_navigate', {'url': LOGIN}),
    'open-fixture': ('browser_navigate', {'url': BASE + '/fixture'}),
    'read': ('browser_snapshot', {}),
    'screen': ('browser_take_screenshot', {'type': 'png'}),
    'diagnostics': ('browser_network_requests', {'static': True}),
    'close': ('browser_close', {}),
}


def command(name):
    """Never accept a tool name, URL, JavaScript or MCP arguments from the caller."""
    if name not in COMMANDS:
        raise ValueError('实验只允许固定页面导航、读取、手动截图和关闭专用窗口。')
    tool, args = COMMANDS[name]
    return tool, dict(args)


def network_summary(text):
    """No query, fragment, credentials, headers or body in diagnostic output."""
    rows = []
    for line in text.splitlines():
        match = re.search(r'\[(GET|HEAD|POST|PUT|PATCH|DELETE|OPTIONS)\]\s+(https?://\S+)\s+=>\s+(.*)', line)
        if not match:
            continue
        method, url, result = match.groups()
        parsed = urlsplit(url)
        status = re.match(r'\[?(\d{3}|FAILED)\]?', result)
        code = re.search(r'net::ERR_[A-Z_]+', result)
        rows.append({'method': method, 'host': parsed.hostname, 'path': parsed.path[:250],
                     'status': status.group(1) if status else 'unknown',
                     **({'error': code.group(0)} if code else {})})
    return rows[-150:]
