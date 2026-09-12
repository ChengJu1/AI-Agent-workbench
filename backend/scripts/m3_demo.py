# 运行 M3 制度问答命令行演示，并检查来源信息与 MCP 审计日志。
# 使用前需要启动后端，并在 backend/.env 中配置有效模型密钥。
import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_json(url, method="GET", body=None):
    headers = {}
    data = None

    if body is not None:
        headers["Content-Type"] = "application/json"
        body_text = json.dumps(body, ensure_ascii=False)
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


def stream_policy_question(api_base, conversation_id, question):
    url = (
        api_base
        + "/api/conversations/"
        + conversation_id
        + "/messages/stream"
    )
    body_text = json.dumps(
        {"content": question},
        ensure_ascii=False,
    )
    request = Request(
        url,
        data=body_text.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    assistant_reply = ""

    with urlopen(request) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()

            if not line.startswith("data: "):
                continue

            event = json.loads(line[6:])

            if event["type"] == "delta":
                text = event["content"]
                assistant_reply += text
                print(text, end="", flush=True)
            elif event["type"] == "error":
                raise RuntimeError(event["content"])

    print()
    return assistant_reply


def find_policy_agent(agents):
    for agent in agents:
        if agent["id"] == "policy_qa_assistant":
            return agent

    return None


def check_success_reply(assistant_reply):
    required_texts = [
        "GPU资源申请管理制度",
        "GPU-001",
        "gpu-application.md",
    ]

    for required_text in required_texts:
        if required_text not in assistant_reply:
            raise RuntimeError(
                "Agent 回复缺少来源信息：" + required_text
            )


def check_mcp_audit_logs(audit_logs):
    successful_actions = []

    for audit_log in audit_logs:
        if audit_log["tool_type"] != "mcp":
            continue
        if audit_log["status"] != "success":
            continue

        successful_actions.append(audit_log["action"])

    if "search_policy" not in successful_actions:
        raise RuntimeError("审计日志缺少 search_policy 成功记录")

    if "get_policy_detail" not in successful_actions:
        raise RuntimeError(
            "审计日志缺少 get_policy_detail 成功记录"
        )


def run_demo(api_base, question):
    agents = request_json(api_base + "/api/agents")
    selected_agent = find_policy_agent(agents)

    if selected_agent is None:
        raise RuntimeError("没有找到 policy_qa_assistant")

    conversation = request_json(
        api_base + "/api/conversations",
        method="POST",
        body={"agent_id": selected_agent["id"]},
    )
    conversation_id = conversation["conversation_id"]

    print("Agent：" + selected_agent["name"])
    print("会话：" + conversation_id)
    print("问题：" + question)
    print("Agent 回复：")

    assistant_reply = stream_policy_question(
        api_base,
        conversation_id,
        question,
    )
    check_success_reply(assistant_reply)

    audit_logs = request_json(
        (
            api_base
            + "/api/conversations/"
            + conversation_id
            + "/audit-logs"
        )
    )
    check_mcp_audit_logs(audit_logs)

    print("MCP 审计日志：")
    print(json.dumps(audit_logs, ensure_ascii=False, indent=2))
    print("M3 制度查询成功路径验收通过。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--api-base",
        default="http://localhost:8000",
    )
    parser.add_argument(
        "--question",
        default="申请 GPU 资源需要满足什么条件？",
    )
    arguments = parser.parse_args()

    try:
        run_demo(
            arguments.api_base.rstrip("/"),
            arguments.question,
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
