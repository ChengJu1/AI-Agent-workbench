# 通过白名单和参数校验安全地调用本地工时 CLI。
# 所有命令都使用固定参数执行，不允许模型自由运行 Shell。
import json
import subprocess
import sys
from pathlib import Path

from pydantic import ValidationError

from app.tool_schemas import validate_tool_payload


class CliAdapterError(RuntimeError):
    pass


class CliAdapter:
    def __init__(self):
        self._timesheet_cli_path = (
            Path(__file__).resolve().parents[2]
            / "tools"
            / "timesheet_cli.py"
        )

    def validate(
        self,
        agent,
        tool_name,
        action,
        payload,
    ):
        selected_tool = None

        for configured_tool in agent.tools: # 在agent有的工具里遍历找一个与输入的工具名相同的 然后存入selected_tool
            if configured_tool.name == tool_name:
                selected_tool = configured_tool
                break

        if selected_tool is None:
            raise CliAdapterError(
                f"Agent 不允许使用工具：{tool_name}"
            )

        if action not in selected_tool.actions: # 如果模型请求的action不在规定的tool_action里 不许执行
            raise CliAdapterError(
                f"Agent 不允许执行 action：{action}"
            )

        try:
            validated_payload = validate_tool_payload(
                action,
                payload,
            )
        except (ValidationError, ValueError) as error:
            raise CliAdapterError(
                f"参数校验失败：{error}"
            ) from error

        return validated_payload

    def execute(
        self,
        agent,
        tool_name,
        action,
        payload,
        approved=False,
    ):
        validated_payload = self.validate( # 先校验数据
            agent,
            tool_name,
            action,
            payload,
        )

        # 是否在action规定的需要permission的action范围内
        needs_approval = (
            action in agent.permissions.require_approval
        )

        if needs_approval and not approved:
            raise PermissionError(
                f"{action} 需要人工确认"
            )

        if action == "submit_timesheet":
            validated_payload["confirmed"] = True

        command = [
            sys.executable,
            str(self._timesheet_cli_path),
            action,
            "--payload",
            json.dumps(
                validated_payload,
                ensure_ascii=False,
            ),
        ]

        # 启动子程序，等待它执行结束，然后拿回执行结果。
        completed_process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        output = completed_process.stdout.strip()

        if not output:
            output = completed_process.stderr.strip()

        try:
            result = json.loads(output)
        except json.JSONDecodeError as error:
            raise CliAdapterError(
                f"CLI 返回的不是合法 JSON：{output}"
            ) from error

        if completed_process.returncode != 0:
            error_message = result.get(
                "error",
                "CLI 执行失败",
            )
            raise CliAdapterError(error_message)

        if result.get("ok") is not True:
            error_message = result.get(
                "error",
                "CLI 执行失败",
            )
            raise CliAdapterError(error_message)

        return result["result"]
