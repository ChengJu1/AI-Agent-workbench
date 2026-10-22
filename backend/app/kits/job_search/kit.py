"""Job-search kit: the ledger, profiles, kits, resume drafts and interview prep of the job-search Agent.

The core knows this kit only through app.kits.registry; nothing here is required by other Agents.
"""
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.kits.job_search.actions import ApplicationActions
from app.kits.job_search.api import router
from app.kits.job_search.application_store import ApplicationStore
from app.kits.job_search.manifest import MANIFEST
from app.kits.job_search.models import (ApplicationRef, ApplicationSaveArgs, InterviewPrepArgs, PrepareKitArgs, ReadFormArgs,
                                        TailorResumeArgs)
from app.kits.job_search.profile_store import ProfileStore

ID = MANIFEST['id']
SCHEMA = Path(__file__).with_name('schema.sql')
PROMPT = '## 投递台账\n平台不会替用户填写或提交网申，只帮用户准备和记录。1) 用户发来岗位或要投递时，先 application_list 查重，再 application_save 记入台账（公司、岗位、链接、截止日期）；2) 用户打开网申表单后，browser_read 找到表单页，application_read_form 只读读取字段；3) application_profiles 取审阅过的资料，application_prepare_kit 生成资料包：能对应资料的用 profile 路径，用户在对话中告诉你的用 user，自我评价、项目描述、开放题按岗位 JD 起草用 inferred；资料和对话中都没有的不要编造；4) 告诉用户去任务页的投递台账逐项复制，自己填写、自己提交，并提醒核对草稿内容；5) 用户告诉你已投递、收到笔试或面试时，用 application_save 更新 stage 和日程（next_event_at + next_event）。6) 用户要按岗位改简历时，先确保 JD 已存进台账，再用 application_tailor_resume 生成草稿并说明要去资料档案审阅保存；要准备面试时用 application_save_interview_prep。两者都只基于用户资料、JD 和知识库，不编造经历。不要用 browser_prepare_actions 在网申表单上填写、点击或提交，不要声称已经填写或投递。'


class Args(BaseModel):
    model_config = ConfigDict(extra='forbid')


DEFINITIONS = {
    'application_list': (Args, '列出投递台账：公司、岗位、链接、阶段、截止日期、下一个日程、是否已有资料包。加岗位前先查重。'),
    'application_read': (ApplicationRef, '读取一条台账记录的详情、资料包和变更历史。'),
    'application_save': (ApplicationSaveArgs, '新增或修改台账记录（只写本机台账，不访问网站）。新增需 company；修改传 application_id，只改你给出的字段。读到岗位描述时把 JD 原文存进 jd，供定制简历和面试准备使用。日期用 YYYY-MM-DD，日程用 YYYY-MM-DD HH:MM 并写明日程内容。只在用户明确告知时改 stage（如用户说已投递、收到笔试），不要自行推断已投递。'),
    'application_profiles': (Args, '读取用户审阅保存过的资料版本（data），生成资料包时引用其 id、version 和字段路径。'),
    'application_read_form': (ReadFormArgs, '只读读取当前网申表单的结构：每个字段的 key、名称、分组、控件类型、是否必填、当前值、原生下拉的选项。不点击、不展开、不填写。'),
    'application_prepare_kit': (PrepareKitArgs, '为台账中的岗位生成资料包，保存后用户在台账逐项复制、自己填写和提交。每项给 key（来自 application_read_form，没有读表时给 label）和来源：profile（ref 为资料路径如 basics.name、education.0.period.start，version 等于 profile_version；日期用 transform "date:month" 指定精度；页面选项说法不同用 transform "option:<选项原文>"）、file（附件 ID，提示用户上传哪个文件）、user（用户在对话中告诉你的值，填 value）、inferred（你按岗位 JD 起草的长答案，填 value，会标为草稿）。资料和对话中都没有的必填项不要编造，平台会列为“请自行填写”。'),
    'application_tailor_resume': (TailorResumeArgs, '按台账里这个岗位的 JD 定制简历：以用户审阅过的资料版本为底稿，只能调整顺序、取舍条目和改写经历描述；学校、学历、公司、职位、起止时间、联系方式必须与原档案完全一致，不能新增经历或技能，否则会被拒绝。另存为新的资料档案草稿，原档案不动，用户审阅后才能使用。同时给出匹配度（0-100）、已覆盖和缺失的关键词、修改建议，建议里不要怂恿编造经历。'),
    'application_save_interview_prep': (InterviewPrepArgs, '为台账里的岗位保存面试准备：按 技术/项目/行为/岗位理解/反问 分类列出可能的问题和回答要点；要点只能基于用户资料、JD 和知识库，based_on 写明依据；资料里没有的经历不要替用户编。'),
}


class JobSearchRuntime:
    """Per-process services of the kit; the platform dispatches the kit's tools here."""

    def __init__(self, database, platform):
        self.applications = ApplicationStore(database)
        self.profiles = ProfileStore(database)
        self.actions = ApplicationActions(self.applications, self.profiles, platform)

    def dispatch(self, conversation_id, name, arguments):
        return self.actions.dispatch(conversation_id, name, arguments)


def build(database, platform):
    return JobSearchRuntime(database, platform)


def prompt(agent):
    return PROMPT


def state(connection, conversation_id, agent):
    """Ledger and profiles are workspace-wide; only ids, versions and stages, never field values."""
    return {
        'applications': [dict(row) for row in connection.execute(
            'SELECT id,revision,stage,company,position FROM applications ORDER BY updated_at DESC,rowid DESC LIMIT 100')],
        'application_count': connection.execute('SELECT COUNT(*) FROM applications').fetchone()[0],
        'profiles': [dict(row) for row in connection.execute(
            "SELECT p.id,p.latest_version,(SELECT MAX(v.version) FROM profile_versions v "
            "WHERE v.profile_id=p.id AND v.review_state='reviewed') AS reviewed_version FROM profiles p ORDER BY p.id")],
    }


def migrate(connection):
    columns = {column[1] for column in connection.execute('PRAGMA table_info(applications)')}
    for field in ('jd', 'tailoring', 'interview_prep'):
        if field not in columns:
            connection.execute(f"ALTER TABLE applications ADD COLUMN {field} TEXT NOT NULL DEFAULT '{'' if field == 'jd' else '{}'}'")
    # The former task-execution capability became this kit.
    connection.execute('UPDATE agent_platform_capabilities SET capabilities=REPLACE(capabilities,?,?) WHERE capabilities LIKE ?',
                       ('"tasks"', '"applications"', '%"tasks"%'))
