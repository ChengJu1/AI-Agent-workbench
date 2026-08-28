# 提供查询日程、生成工时草稿和提交模拟工时三个 CLI action。
# 所有输入和输出都使用 JSON，方便 CLI Adapter 受控调用。
import argparse
import json
import sys
from pathlib import Path
from uuid import uuid4


MOCK_CALENDAR_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "mock_calendar.json"
)


def load_payload(raw_payload): # 把待处理的payload数据加载出来
    payload = json.loads(raw_payload)

    if not isinstance(payload, dict):
        raise ValueError("payload 必须是 JSON 对象")

    return payload


def query_calendar(payload): # 实现查询日历工具
    date = payload.get("date")

    if not isinstance(date, str) or not date: # 类型校验
        raise ValueError("query_calendar 需要非空 date")

    calendar = json.loads(
        MOCK_CALENDAR_PATH.read_text(encoding="utf-8")
    )
    events = calendar.get(date, [])
    total_hours = 0

    for event in events:
        total_hours = total_hours + event["hours"] # 简单遍历计算总工时

    return {
        "action": "query_calendar",
        "date": date,
        "events": events,
        "total_hours": total_hours,
    }


def draft_timesheet(payload): # 合法校验 没问题后返回normalized结果 校验对象是query_calendar的输出
    records = payload.get("records")

    if not isinstance(records, list) or not records:
        raise ValueError("draft_timesheet 需要非空 records")

    normalized_records = []

    for record in records:
        if not isinstance(record, dict):
            raise ValueError("每条工时记录必须是 JSON 对象")

        date = record.get("date")
        task = record.get("task")
        hours = record.get("hours")
        note = record.get("note", "")

        if not isinstance(date, str) or not date:
            raise ValueError("工时记录缺少 date")

        if not isinstance(task, str) or not task:
            raise ValueError("工时记录缺少 task")

        if (
            isinstance(hours, bool)
            or not isinstance(hours, (int, float))
            or hours <= 0
        ):
            raise ValueError("hours 必须是正数")

        if hours * 2 != int(hours * 2):
            raise ValueError("hours 必须以 0.5 小时为单位")

        if not isinstance(note, str):
            raise ValueError("note 必须是字符串")

        normalized_records.append(
            {
                "date": date,
                "task": task,
                "hours": float(hours),
                "note": note,
            }
        )

    total_hours = 0

    for record in normalized_records:
        total_hours = total_hours + record["hours"]

    warnings = []

    if total_hours > 8:
        warnings.append("草稿总工时超过 8 小时，请检查")

    return {
        "action": "draft_timesheet",
        "records": normalized_records,
        "total_hours": total_hours,
        "warnings": warnings,
    }


def submit_timesheet(payload):
    if payload.get("confirmed") is not True:
        raise PermissionError("submit_timesheet 尚未获得人工确认")

    draft = payload.get("draft") # draft_timesheet 输出

    if not isinstance(draft, dict):
        raise ValueError("submit_timesheet 需要 draft")

    records = draft.get("records")

    if not isinstance(records, list) or not records:
        raise ValueError("draft 中没有可提交的工时记录")

    return {
        "action": "submit_timesheet",
        "status": "submitted",
        "submission_id": str(uuid4()),
        "records": records,
        "total_hours": draft.get("total_hours"),
    }


ALLOWED_ACTIONS = [
    "query_calendar",
    "draft_timesheet",
    "submit_timesheet",
]


def main():
    parser = argparse.ArgumentParser() # 创建一个空的命令行参数登记表。
    parser.add_argument("action", choices=ALLOWED_ACTIONS) # 命令中必须提供一个名为 action 的位置参数, 这个参数只能有三个选择
    parser.add_argument("--payload", required=True) # 命令中必须有一个--payload的参数
    arguments = parser.parse_args() # 解析用户在终端的输出

    try:
        payload = load_payload(arguments.payload) # 根据不同action执行对应函数

        if arguments.action == "query_calendar":
            result = query_calendar(payload)
        elif arguments.action == "draft_timesheet":
            result = draft_timesheet(payload)
        else:
            result = submit_timesheet(payload)
    except (
        OSError,
        json.JSONDecodeError,
        ValueError,
        PermissionError,
    ) as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(error),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "result": result,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
