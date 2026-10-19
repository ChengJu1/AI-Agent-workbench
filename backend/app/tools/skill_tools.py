"""为本轮可用 Skill 提供受绑定范围限制的只读正文加载工具。"""
import json
import logging

import anyio
from claude_agent_sdk import create_sdk_mcp_server, tool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.errors import ServiceError


logger = logging.getLogger(__name__)
SERVER_NAME = "workbench_skills"
ACTION = "load_skill"
ALLOWED_TOOL = f"mcp__{SERVER_NAME}__{ACTION}"


class LoadSkillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    skill_id: str = Field(min_length=1, max_length=100, strict=True)


class SkillToolsService:
    def __init__(self, skill_store, audit_store):
        self.skill_store = skill_store
        self.audit_store = audit_store

    def execute(self, conversation_id, agent, arguments, loads):
        skill = None
        error = None
        try:
            request = LoadSkillRequest.model_validate(arguments)
            skill = next((item for item in agent.bound_skills if item.id == request.skill_id), None)
            if skill is None or not self.skill_store.is_bound(agent.id, request.skill_id):
                raise ServiceError("该 Skill 不在当前 Agent 的本轮可用范围内，或绑定已解除。", 403)
        except ValidationError:
            error = "读取参数不正确，请提供目录中有效的 skill_id。"
        except ServiceError as exception:
            error = str(exception)
        except Exception:
            logger.exception("读取 Skill 失败: agent_id=%s", agent.id)
            error = "Skill 暂时无法读取，请稍后重试。"
        reference = {"id": skill.id, "name": skill.name, "version": skill.version} if skill and not error else None
        try:
            self.audit_store.add_audit_log(
                conversation_id, agent.id, SERVER_NAME, ACTION, arguments,
                "failed" if error else "success", result=reference, error=error, tool_type="skill",
            )
        except Exception:
            logger.exception("保存 Skill 读取记录失败: agent_id=%s", agent.id)
            error = "无法保存 Skill 读取记录，请稍后重试。"
        if error:
            return {"content": [{"type": "text", "text": error}], "is_error": True}
        # 正文采用本轮开始时固定的版本，而不是工具调用时的新版本。
        loads.record(skill)
        return {"content": [{"type": "text", "text": json.dumps({
            **reference, "description": skill.description, "content": skill.content,
        }, ensure_ascii=False)}]}

    def create_server(self, conversation_id, agent, loads):
        schema = LoadSkillRequest.model_json_schema()
        schema["properties"]["skill_id"]["enum"] = [skill.id for skill in agent.bound_skills]

        async def handle(arguments):
            return await anyio.to_thread.run_sync(self.execute, conversation_id, agent, arguments, loads)

        read = tool(
            ACTION,
            "按需读取当前 Agent 可用 Skill 的完整工作步骤。先根据系统提示中的名称和用途选择相关 Skill，"
            "再传入对应 skill_id；与任务无关时不要读取，不要批量读取全部 Skill。"
            "同一轮一般只需读取一次。返回本轮固定版本的名称、说明、版本和正文。"
            "读取规则不等于执行了规则中的检查，也不会开放任何额外工具权限。",
            schema,
        )(handle)
        return create_sdk_mcp_server(name=SERVER_NAME, version="1.0.0", tools=[read])
