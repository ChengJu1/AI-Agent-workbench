"""Reviewable, versioned personal profiles. Values are resolved by path, never retyped by the model."""
import datetime
import re
from typing import Literal

from pydantic import Field, model_validator

from app.errors import ServiceError
from app.models.agents import StrictModel

KEY = r'^[A-Za-z][A-Za-z0-9_]{0,59}$'
# Identity documents and bank cards never go into profiles.
PROTECTED = [re.compile(r'(?<!\d)\d{17}[\dXx](?!\d)'), re.compile(r'(?<!\d)\d{16,19}(?!\d)')]


class DateValue(StrictModel):
    """A date with explicit precision, so month-only facts are never padded with a day."""
    precision: Literal['year', 'month', 'day']
    year: int = Field(ge=1900, le=2200)
    month: int | None = Field(default=None, ge=1, le=12)
    day: int | None = Field(default=None, ge=1, le=31)

    @model_validator(mode='after')
    def consistent(self):
        need = {'year': (False, False), 'month': (True, False), 'day': (True, True)}[self.precision]
        if (self.month is not None, self.day is not None) != need:
            raise ValueError('日期字段与精度不一致。')
        if self.day:
            datetime.date(self.year, self.month, self.day)
        return self

    def key(self):
        return (self.year, self.month or 0, self.day or 0)

    def format(self, precision):
        """Render at the requested precision; refuses to invent missing parts."""
        order = ['year', 'month', 'day']
        if order.index(precision) > order.index(self.precision):
            raise ServiceError(f'资料只有{self.precision}精度，不能写成{precision}精度，请补充资料。', 422)
        parts = [f'{self.year:04d}', f'{self.month:02d}' if self.month else '', f'{self.day:02d}' if self.day else '']
        return '-'.join(parts[:order.index(precision) + 1])


class DateRange(StrictModel):
    start: DateValue
    end: DateValue | None = None
    present: bool = False

    @model_validator(mode='after')
    def ordered(self):
        if self.present == (self.end is not None):
            raise ValueError('结束时间与“至今”需且仅需提供一个。')
        if self.end:
            # Compare only at the precision both ends actually have.
            rank = {'year': 1, 'month': 2, 'day': 3}
            common = min(rank[self.start.precision], rank[self.end.precision])
            if self.end.key()[:common] < self.start.key()[:common]:
                raise ValueError('结束时间不能早于开始时间。')
        return self


class Period(StrictModel):
    organization: str = Field(min_length=1, max_length=200)
    title: str = Field(default='', max_length=200)
    period: DateRange
    description: str = Field(default='', max_length=4000)


class Education(StrictModel):
    school: str = Field(min_length=1, max_length=200)
    degree: str = Field(default='', max_length=60)
    major: str = Field(default='', max_length=200)
    period: DateRange
    gpa: str = Field(default='', max_length=40)


class ProfileData(StrictModel):
    basics: dict[str, str] = Field(default_factory=dict)
    education: list[Education] = Field(default_factory=list, max_length=20)
    experience: list[Period] = Field(default_factory=list, max_length=50)
    projects: list[Period] = Field(default_factory=list, max_length=50)
    skills: list[str] = Field(default_factory=list, max_length=200)
    answers: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode='after')
    def safe(self):
        for group in (self.basics, self.answers):
            for key, value in group.items():
                if not re.match(KEY, key) or len(value) > 4000:
                    raise ValueError(f'字段 {key} 名称需为英文标识、内容不超过 4000 字符。')
        if any(len(s) > 100 for s in self.skills):
            raise ValueError('单项技能不超过 100 字符。')
        text = self.model_dump_json()
        if any(p.search(text) for p in PROTECTED):
            raise ValueError('资料中疑似包含身份证号或银行卡号，请不要存入资料。')
        return self


class ProfileSave(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    data: ProfileData
    source_file_id: str | None = Field(default=None, pattern=r'^file_[a-f0-9]{32}$')
    expected_version: int | None = Field(default=None, ge=1)
