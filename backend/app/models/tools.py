# 定义三个工时 action 的参数格式和业务校验规则。
# CLI Adapter 会先通过这些模型检查参数，再执行命令。
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QueryCalendarInput(StrictToolInput):
    date: str = Field(
        pattern=r"^\d{4}-\d{2}-\d{2}$"
    )

    @field_validator("date")
    @classmethod
    def validate_date(cls, value):
        date.fromisoformat(value)
        return value


class TimesheetRecord(QueryCalendarInput):
    task: str = Field(min_length=1)
    hours: float = Field(gt=0, allow_inf_nan=False)
    note: str = ""

    @field_validator("hours", mode="before")
    @classmethod
    def reject_boolean_hours(cls, value):
        if isinstance(value, bool):
            raise ValueError("hours 必须是数字，不能是布尔值")
        return value

    @model_validator(mode="after")
    def validate_hours(self):
        doubled_hours = self.hours * 2
        rounded_hours = round(doubled_hours)

        if doubled_hours != rounded_hours:
            raise ValueError(
                "hours 必须以 0.5 小时为单位"
            )

        return self


class DraftTimesheetInput(StrictToolInput):
    records: list[TimesheetRecord] = Field(
        min_length=1
    )


class TimesheetDraft(StrictToolInput): # 校验工时计算是否一致 正确
    records: list[TimesheetRecord] = Field(
        min_length=1
    )
    total_hours: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_total_hours(self):
        calculated_total = 0

        for record in self.records:
            calculated_total = (
                calculated_total + record.hours
            )

        difference = abs(
            calculated_total - self.total_hours
        )

        if difference > 0.001:
            raise ValueError(
                "total_hours 与 records 中的工时总和不一致"
            )

        return self


class SubmitTimesheetInput(StrictToolInput):
    draft: TimesheetDraft


def validate_tool_payload(action, payload):  # 格式检查
    if action == "query_calendar":
        validated_input = (
            QueryCalendarInput.model_validate(payload)
        )
    elif action == "draft_timesheet":
        validated_input = (
            DraftTimesheetInput.model_validate(payload)
        )
    elif action == "submit_timesheet":
        validated_input = (
            SubmitTimesheetInput.model_validate(payload)
        )
    else:
        raise ValueError(
            f"未知 action：{action}"
        )

    validated_payload = validated_input.model_dump()

    return validated_payload
