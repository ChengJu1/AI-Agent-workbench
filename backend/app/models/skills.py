"""用户 Skill 是带版本的文本规则，不携带执行权限。"""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class SkillDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    content: str = Field(min_length=1, max_length=30000)


class SkillUpdate(SkillDefinition):
    expected_version: int = Field(ge=1, strict=True)


class SkillReference(BaseModel):
    id: str
    name: str
    version: int = Field(ge=1, strict=True)


class SkillInfo(SkillDefinition, SkillReference):
    created_at: str
    updated_at: str


class AgentSkillsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    skill_ids: list[Annotated[str, StringConstraints(min_length=1, max_length=100)]] = Field(
        default_factory=list
    )
    skill_versions: dict[str, Annotated[int, Field(ge=1, strict=True)]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def unique_skills(self):
        if len(self.skill_ids) != len(set(self.skill_ids)):
            raise ValueError("Skill 不能重复选择")
        if not set(self.skill_versions).issubset(self.skill_ids):
            raise ValueError("版本只能指定给已选择的 Skill")
        return self


class SkillImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=40000)


class SkillImportPreview(SkillDefinition):
    ignored_fields: list[str] = Field(default_factory=list)
