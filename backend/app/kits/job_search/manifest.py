"""Job-search kit manifest: plain data the core catalog reads without importing the kit itself."""
MANIFEST = {
    'id': 'applications',
    'name': '投递台账',
    'description': '维护投递台账（岗位、截止日期、阶段、日程），只读读取网申表单，按审阅过的资料生成逐项可复制的资料包，按岗位定制简历草稿和准备面试。不会替用户填写或提交。',
    'tools': ['application_list', 'application_read', 'application_save', 'application_profiles', 'application_read_form', 'application_prepare_kit', 'application_tailor_resume', 'application_save_interview_prep'],
    'module': 'app.kits.job_search.kit',
}
