# 运行完整的 M2 命令行演示流程，包括对话、审批和审计查询。
# 使用前需要先启动后端并配置 WORKBENCH_DEEPAGENTS_API_KEY。
import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_json(url, method="GET", body=None):
    headers = {}
    data = None

    if body is not None:
        headers["Content-Type"] = "application/json"
        body_text = json.dumps(
            body,
            ensure_ascii=False,
        )
        data = body_text.encode("utf-8")

    request = Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )

    with urlopen(request) as response:
        response_text = response.read().decode("utf-8")

    return json.loads(response_text)


def stream_demo_message(api_base, conversation_id):
    url = (
        api_base
        + "/api/conversations/"
        + conversation_id
        + "/messages/stream"
    )
    body = {
        "content": (
            "请查询 2026-08-27 的日程，生成工时草稿，"
            "然后申请提交这份工时。"
        )
    }
    body_text = json.dumps(
        body,
        ensure_ascii=False,
    )

    request = Request(
        url,
        data=body_text.encode("utf-8"),
        headers={
            "Content-Type": "application/json"
        },
        method="POST",
    )

    pending_action = None

    with urlopen(request) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()

            if not line.startswith("data: "):
                continue

            event = json.loads(line[6:])

            if event["type"] == "delta":
                print(event["content"], end="", flush=True)
            elif event["type"] == "approval_required":
                pending_action = event["action"]
            elif event["type"] == "error":
                raise RuntimeError(event["content"])

    print()

    return pending_action


def run_demo(api_base, decision):
    agents = request_json(api_base + "/api/agents")
    selected_agent = None

    for agent in agents:
        if agent["id"] == "timesheet_assistant":
            selected_agent = agent
            break

    if selected_agent is None:
        raise RuntimeError("没有找到 timesheet_assistant")

    conversation = request_json(
        api_base + "/api/conversations",
        method="POST",
        body={"agent_id": selected_agent["id"]},
    )
    conversation_id = conversation["conversation_id"]

    print("Agent：" + selected_agent["name"])
    print("会话：" + conversation_id)
    print("Agent 回复：")

    pending_action = stream_demo_message(
        api_base,
        conversation_id,
    )

    if pending_action is None:
        raise RuntimeError(
            "模型没有生成等待确认的提交操作"
        )

    print(
        "待确认操作："
        + json.dumps(
            pending_action,
            ensure_ascii=False,
            indent=2,
        )
    )

    approved = decision == "approve"
    decision_result = request_json(
        (
            api_base
            + "/api/pending-actions/"
            + pending_action["id"]
            + "/decision"
        ),
        method="POST",
        body={"approved": approved},
    )

    print(
        "处理结果："
        + json.dumps(
            decision_result,
            ensure_ascii=False,
            indent=2,
        )
    )

    audit_logs = request_json(
        (
            api_base
            + "/api/conversations/"
            + conversation_id
            + "/audit-logs"
        )
    )

    print(
        "审计日志："
        + json.dumps(
            audit_logs,
            ensure_ascii=False,
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--api-base",
        default="http://localhost:8000",
    )
    parser.add_argument(
        "--decision",
        choices=["approve", "cancel"],
        default="approve",
    )
    arguments = parser.parse_args()

    try:
        run_demo(
            arguments.api_base.rstrip("/"),
            arguments.decision,
        )
    except HTTPError as error:
        error_text = error.read().decode("utf-8")
        print("HTTP 请求失败：" + error_text)
        return 1
    except URLError as error:
        print("无法连接后端：" + str(error.reason))
        return 1
    except Exception as error:
        print("演示失败：" + str(error))
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
