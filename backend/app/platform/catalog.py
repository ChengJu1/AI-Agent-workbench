from typing import Literal

Capability = Literal['files', 'web', 'browser']
CATALOG = [
    {'id': 'files', 'name': '文件解析', 'description': '读取当前会话中由用户上传的 PDF、DOCX、TXT、MD、CSV、JSON 文件；不扫描本机目录。'},
    {'id': 'web', 'name': '联网检索', 'description': '搜索公开网页、读取正文并返回真实来源链接；不能读取内网、登录态或任意本机地址。'},
    {'id': 'browser', 'name': '受控浏览器', 'description': '独立浏览器打开公开网站、查看页面；填表、上传和点击需用户逐批确认。登录由用户接手。'},
]
TOOL_CAPABILITIES = {
    'list_files': 'files', 'read_file': 'files', 'web_search': 'web', 'web_read': 'web',
    'list_browser_sessions': 'browser', 'browser_open': 'browser', 'browser_read': 'browser', 'browser_prepare_actions': 'browser', 'browser_close': 'browser',
}
