from typing import Literal

Capability = Literal['files', 'web', 'browser', 'tracking', 'applications']
CATALOG = [
    {'id': 'applications', 'name': '投递台账', 'description': '维护投递台账（岗位、截止日期、阶段、日程），只读读取网申表单，按审阅过的资料生成逐项可复制的资料包。不会替用户填写或提交。'},
    {'id': 'tracking', 'name': '记录与跟踪', 'description': '查询当前 Agent 的执行记录、建立只读状态跟踪方案；定期检查需用户启用，网页访问还需对应能力。'},
    {'id': 'files', 'name': '文件解析', 'description': '读取当前会话中由用户上传的 PDF、DOCX、TXT、MD、CSV、JSON 文件；或用户明确关联的单个本机文件；不扫描目录。'},
    {'id': 'web', 'name': '联网检索', 'description': '搜索公开网页、读取正文并返回真实来源链接；不能读取内网、登录态或任意本机地址。'},
    {'id': 'browser', 'name': '受控浏览器', 'description': '独立浏览器打开公开网站、查看页面；填表、上传和点击需用户逐批确认。登录由用户接手。'},
]
TOOL_CAPABILITIES = {
    'save_work_item': 'tracking', 'list_work_items': 'tracking', 'read_work_item': 'tracking',
    'list_records': 'tracking', 'create_tracking': 'tracking', 'list_tracking': 'tracking', 'read_tracking': 'tracking',
    'check_file': 'files', 'update_file': 'files', 'list_files': 'files', 'read_file': 'files', 'web_search': 'web', 'web_read': 'web',
    'application_list': 'applications', 'application_read': 'applications', 'application_save': 'applications',
    'application_profiles': 'applications', 'application_read_form': 'applications', 'application_prepare_kit': 'applications',
    'list_browser_sessions': 'browser', 'browser_open': 'browser', 'browser_read': 'browser', 'browser_prepare_actions': 'browser', 'browser_close': 'browser',
}
