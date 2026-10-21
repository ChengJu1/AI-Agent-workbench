"""Application ledger: jobs the user tracks, their stage and dates, and a copy-ready kit for filling forms by hand.

The platform never writes to an employer's site. It reads, drafts and keeps records; the user fills and submits.
"""
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from app.models.agents import StrictModel

Stage = Literal['saved', 'preparing', 'applied', 'test', 'interview', 'offer', 'rejected', 'withdrawn']
DATE = r'^(|\d{4}-\d{2}-\d{2})$'
DATETIME = r'^(|\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?)$'
TRANSFORM = r'^(|date:(year|month|day)(:[-/.年月]{1,2})?|option:.{1,190})$'


def check_url(url):
    if url:
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('链接必须是有效网页地址，不能包含账号密码。')


class ApplicationFields(StrictModel):
    company: str = Field(min_length=1, max_length=120)
    position: str = Field(default='', max_length=160)
    url: str = Field(default='', max_length=3000)
    deadline: str = Field(default='', pattern=DATE)
    next_event_at: str = Field(default='', pattern=DATETIME)
    next_event: str = Field(default='', max_length=200)
    note: str = Field(default='', max_length=3000)

    @model_validator(mode='after')
    def valid(self):
        self.company, self.position = self.company.strip(), self.position.strip()
        if not self.company:
            raise ValueError('公司名称不能为空。')
        check_url(self.url)
        if self.next_event_at and not self.next_event.strip():
            raise ValueError('设置了日程时间，请写明是什么日程（如笔试、一面）。')
        return self


class ApplicationSave(ApplicationFields):
    expected_revision: int | None = Field(default=None, ge=1, strict=True)


class StageChange(StrictModel):
    expected_revision: int = Field(ge=1, strict=True)
    stage: Stage
    note: str = Field(default='', max_length=500)


class KitSource(StrictModel):
    kind: Literal['profile', 'file', 'user', 'inferred']
    ref: str = Field(default='', max_length=200)
    version: int | None = Field(default=None, ge=1)


class KitItem(StrictModel):
    key: str | None = Field(default=None, pattern=r'^f\d{1,4}$')  # Field key from application_read_form, when a form was read.
    label: str = Field(default='', max_length=120)
    section: str = Field(default='', max_length=60)
    source: KitSource
    transform: str = Field(default='', max_length=200, pattern=TRANSFORM)
    value: str = Field(default='', max_length=4000)
    note: str = Field(default='', max_length=300)

    @model_validator(mode='after')
    def named(self):
        if not self.key and not self.label.strip():
            raise ValueError('资料包条目需要表单字段 key 或字段名称。')
        if self.source.kind in ('user', 'inferred') and not self.value.strip():
            raise ValueError('用户在对话中提供或由你起草的条目必须给出 value。')
        return self


class KitEdit(StrictModel):
    expected_revision: int = Field(ge=1, strict=True)
    index: int = Field(ge=0, le=199)
    value: str = Field(max_length=4000)


# ---------- Agent tool arguments ----------
class ApplicationRef(StrictModel):
    application_id: str = Field(pattern=r'^app_[a-f0-9]{32}$')


class ApplicationSaveArgs(StrictModel):
    """Agent edits name only the fields they change; the merged record is validated as ApplicationSave."""
    application_id: str | None = Field(default=None, pattern=r'^app_[a-f0-9]{32}$')
    company: str = Field(default='', max_length=120)
    position: str = Field(default='', max_length=160)
    url: str = Field(default='', max_length=3000)
    deadline: str = Field(default='', pattern=DATE)
    next_event_at: str = Field(default='', pattern=DATETIME)
    next_event: str = Field(default='', max_length=200)
    note: str = Field(default='', max_length=3000)
    stage: Stage | None = None


class ReadFormArgs(StrictModel):
    session_id: str = Field(pattern=r'^browser_[a-f0-9]{32}$')


class PrepareKitArgs(ApplicationRef):
    profile_id: str = Field(pattern=r'^profile_[a-f0-9]{32}$')
    profile_version: int = Field(ge=1)
    session_id: str | None = Field(default=None, pattern=r'^browser_[a-f0-9]{32}$')
    items: list[KitItem] = Field(min_length=1, max_length=150)
