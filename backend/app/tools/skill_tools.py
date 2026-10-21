"""在 Agent 的固定版本绑定范围内搜索用途目录，按本轮预算读取完整正文。"""
import json
import logging
import re

import anyio
from app.tools.registry import ToolDefinition
from app.tools.runtime_adapters import to_claude_sdk
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.errors import ServiceError
from app.services.skill_catalog import CATALOG_MAX_CHARS, catalog_entry


logger = logging.getLogger(__name__)
SERVER_NAME = "workbench_skills"
ACTION = "load_skill"
SEARCH_ACTION = "search_skills"
ALLOWED_TOOL = f"mcp__{SERVER_NAME}__{ACTION}"
SEARCH_TOOL = f"mcp__{SERVER_NAME}__{SEARCH_ACTION}"


class LoadSkillRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    skill_id: str = Field(min_length=1, max_length=100, strict=True)


class SearchSkillsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(default="", max_length=200, strict=True)
    limit: int = Field(default=8, ge=1, le=20, strict=True)
    offset: int = Field(default=0, ge=0, strict=True)


def tool_result(value, error=False):
    return {"content": [{"type": "text", "text": value if error else json.dumps(value, ensure_ascii=False)}],
            **({"is_error": True} if error else {})}


class SkillToolsService:
    def __init__(self, skill_store, audit_store):
        self.skill_store = skill_store
        self.audit_store = audit_store

    def _audit(self, conversation_id, agent, action, arguments, result=None, error=None):
        self.audit_store.add_audit_log(
            conversation_id, agent.id, SERVER_NAME, action, arguments,
            "failed" if error else "success", result=result, error=error, tool_type="skill",
        )

    def _failure(self, conversation_id, agent, action, arguments, error):
        try:
            self._audit(conversation_id, agent, action, arguments, error=error)
        except Exception:
            logger.exception("保存 Skill 工具记录失败: agent_id=%s", agent.id)
            error = "无法保存 Skill 工具记录，请稍后重试。"
        return tool_result(error, error=True)

    def execute(self, conversation_id, agent, arguments, loads):
        try:
            request = LoadSkillRequest.model_validate(arguments)
            skill = next((item for item in agent.bound_skills if item.id == request.skill_id), None)
            if skill is None or not self.skill_store.is_bound(agent.id, request.skill_id, skill.version):
                raise ServiceError("该 Skill 不在本轮可用范围内，或绑定版本已切换，请在下一轮重试。", 403)
            reference = {"id": skill.id, "name": skill.name, "version": skill.version}
            # 预算检查、成功审计和读取记录在同一锁内完成，防止并行读取绕过预算。
            budget = loads.record(skill, lambda: self._audit(conversation_id, agent, ACTION, arguments, result=reference))
            return tool_result({**reference, "description": skill.description, "content": skill.content, "budget": budget})
        except ValidationError:
            error = "读取参数不正确，请提供有效的 skill_id。"
        except ServiceError as exception:
            error = str(exception)
        except Exception:
            logger.exception("读取 Skill 失败: agent_id=%s", agent.id)
            error = "Skill 暂时无法读取，请稍后重试。"
        return self._failure(conversation_id, agent, ACTION, arguments, error)

    def search(self, conversation_id, agent, arguments):
        try:
            request = SearchSkillsRequest.model_validate(arguments)
            live = self.skill_store.binding_versions(agent.id)
            terms = re.findall(r"\w+", request.query.casefold())
            candidates = []
            for skill in agent.bound_skills:
                if live.get(skill.id) != skill.version:
                    continue
                name, description = skill.name.casefold(), skill.description.casefold()
                score = sum(3 * (term in name) + (term in description) for term in terms)
                if not terms or score:
                    candidates.append((score, skill))
            candidates.sort(key=lambda item: -item[0])

            def page(matches):
                end = request.offset + len(matches)
                return {"matches": matches, "total_matches": len(candidates),
                        "next_offset": end if end < len(candidates) else None}

            matches = []
            for _, skill in candidates[request.offset:request.offset + request.limit]:
                updated = [*matches, catalog_entry(skill)]
                if len(json.dumps(page(updated), ensure_ascii=False)) > CATALOG_MAX_CHARS:
                    break
                matches = updated
            result = page(matches)
            self._audit(conversation_id, agent, SEARCH_ACTION, arguments, result=result)
            return tool_result(result)
        except ValidationError:
            error = "搜索参数不正确：关键词最多 200 字符，limit 为 1–20，offset 为非负整数。"
        except Exception:
            logger.exception("搜索 Skill 失败: agent_id=%s", agent.id)
            error = "Skill 目录暂时无法搜索，请稍后重试。"
        return self._failure(conversation_id, agent, SEARCH_ACTION, arguments, error)

    def definitions(self, conversation_id, agent, loads):
        async def handle(arguments):
            return await anyio.to_thread.run_sync(self.execute, conversation_id, agent, arguments, loads)

        async def search_handle(arguments):
            return await anyio.to_thread.run_sync(self.search, conversation_id, agent, arguments)

        read = ToolDefinition(
            ACTION, LoadSkillRequest,
            "按需读取当前 Agent 已绑定固定版本 Skill 的完整正文。先根据用途目录或 search_skills 选择相关 Skill，"
            "再传入 skill_id；无关任务不要读取，不要批量读取全部 Skill。"
            "同一 Skill 同一轮通常只读一次，重复返回全文也计入本轮字符预算。"
            "超出预算时拒绝整次读取，不截断正文；返回 budget 中的剩余预算。"
            "读取规则不等于执行了检查，也不会开放额外工具权限。",
            handle,
        )
        search = ToolDefinition(
            SEARCH_ACTION, SearchSkillsRequest,
            "搜索当前 Agent 已绑定且本轮仍有效的 Skill 名称、用途和固定版本，不返回正文，不代表已读取规则。"
            "用空格分隔简短关键词；query 为空时分页浏览全部目录。"
            "通过 next_offset 翻页；无匹配时可改用更短关键词。每次最多 20 条且目录结果不超过 12000 字符。"
            "选择相关 skill_id 后调用 load_skill 读取正文。",
            search_handle,
        )
        # 工具参数不枚举全部 ID，避免大型绑定目录转移到工具 schema 中。
        return [read, search]

    def create_server(self, conversation_id, agent, loads):
        return to_claude_sdk(SERVER_NAME, self.definitions(conversation_id, agent, loads))
