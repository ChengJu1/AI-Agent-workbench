from typing import Literal

from app.kits.registry import MANIFESTS

CORE_CATALOG = [
    {'id': 'tracking', 'name': '记录与跟踪', 'description': '查询当前 Agent 的执行记录、建立只读状态跟踪方案；定期检查需用户启用，网页访问还需对应能力。'},
    {'id': 'files', 'name': '文件解析', 'description': '读取当前会话中由用户上传的 PDF、DOCX、TXT、MD、CSV、JSON 文件；或用户明确关联的单个本机文件；不扫描目录。'},
    {'id': 'web', 'name': '联网检索', 'description': '搜索公开网页、读取正文并返回真实来源链接；不能读取内网、登录态或任意本机地址。'},
    {'id': 'browser', 'name': '受控浏览器', 'description': '独立浏览器打开公开网站、查看页面；填表、上传和点击需用户逐批确认。登录由用户接手。'},
    {'id': 'code', 'name': '项目代码', 'description': '只读浏览、搜索和阅读你为此 Agent 绑定的本机项目目录；不能修改或执行代码，密钥类文件不可见。'},
]
CORE_TOOL_CAPABILITIES = {
    'save_work_item': 'tracking', 'list_work_items': 'tracking', 'read_work_item': 'tracking',
    'list_records': 'tracking', 'create_tracking': 'tracking', 'list_tracking': 'tracking', 'read_tracking': 'tracking',
    'check_file': 'files', 'update_file': 'files', 'list_files': 'files', 'read_file': 'files', 'web_search': 'web', 'web_read': 'web',
    'list_browser_sessions': 'browser', 'browser_open': 'browser', 'browser_read': 'browser', 'browser_prepare_actions': 'browser', 'browser_close': 'browser',
    'code_projects': 'code', 'code_list': 'code', 'code_search': 'code', 'code_read': 'code', 'code_outline': 'code',
}

# Kits (the specialised part of one kind of Agent) add their own capability and tools.
CATALOG = [{key: manifest[key] for key in ('id', 'name', 'description')} for manifest in MANIFESTS] + CORE_CATALOG
TOOL_CAPABILITIES = {**CORE_TOOL_CAPABILITIES, **{tool: manifest['id'] for manifest in MANIFESTS for tool in manifest['tools']}}
Capability = Literal[tuple(entry['id'] for entry in CATALOG)]
