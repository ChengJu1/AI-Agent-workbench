"""Generic records and explicitly enabled, read-only status checks."""
from typing import Literal
from pydantic import Field, model_validator
from app.models.agents import StrictModel


class StatusRule(StrictModel):
    status: str = Field(min_length=1, max_length=80)
    keywords: list[str] = Field(min_length=1, max_length=12)
    terminal: bool = False

    @model_validator(mode='after')
    def bounded_keywords(self):
        if any(not item.strip() or len(item) > 200 for item in self.keywords):
            raise ValueError('状态关键词需为 1–200 字符。')
        self.keywords = list(dict.fromkeys(item.strip() for item in self.keywords))
        return self


class TrackingDefinition(StrictModel):
    title: str = Field(min_length=1, max_length=160)
    url: str = Field(min_length=1, max_length=3000)
    mode: Literal['web', 'browser'] = 'web'
    session_id: str | None = Field(default=None, pattern=r'^browser_[a-f0-9]{32}$')
    selector: str = Field(default='', max_length=500)
    anchor: str = Field(min_length=1, max_length=300)
    interval_minutes: int = Field(default=1440, ge=5, le=43200, strict=True)
    rules: list[StatusRule] = Field(min_length=1, max_length=20)
    record_id: str | None = None

    @model_validator(mode='after')
    def unique_states(self):
        if len({item.status for item in self.rules}) != len(self.rules):
            raise ValueError('状态名称不能重复。')
        if self.mode == 'browser' and not self.session_id:
            raise ValueError('浏览器查询需要明确关联当前会话的页面。')
        return self


class TrackingControl(StrictModel):
    expected_revision: int = Field(ge=1)
    action: Literal['resume', 'pause', 'finish', 'read_notifications']


class TrackingEdit(TrackingDefinition):
    expected_revision: int = Field(ge=1)


class WorkItemSave(StrictModel):
    key: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=160)
    target_url: str = Field(default='', max_length=3000)
    state: Literal['planned', 'blocked', 'cancelled'] = 'planned'
    note: str = Field(default='', max_length=3000)
    next_step: str = Field(default='', max_length=1000)
    item_id: str | None = Field(default=None, pattern=r'^work_[a-f0-9]{32}$')
    expected_revision: int | None = Field(default=None, ge=1, strict=True)

    @model_validator(mode='after')
    def valid_item(self):
        from urllib.parse import urlsplit
        self.key, self.title = self.key.strip(), self.title.strip()
        if not self.key or not self.title:
            raise ValueError('事项标识和名称不能为空。')
        if (self.item_id is None) != (self.expected_revision is None):
            raise ValueError('修改事项必须提供事项 ID 和当前版本。')
        if self.state == 'blocked' and not self.note.strip():
            raise ValueError('受阻事项必须说明原因。')
        if self.target_url:
            parsed = urlsplit(self.target_url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('事项链接必须是有效网页地址，不能包含账号密码。')
        return self
