# 从 backend/agents 读取并校验 Agent 配置、Prompt 和 Skill 文件。
# 加载完成的 Agent 会保存在内存中供后端查询。
import json
from pathlib import Path

from pydantic import ValidationError

from app.config import BACKEND_DIRECTORY
from app.models.agents import AgentManifest, LoadedAgent


class AgentRegistry:
    def __init__(self, agents_directory=None):
        self._agents_directory = Path(agents_directory or BACKEND_DIRECTORY / "agents").resolve()
        self._agents = self._load_agents()

    def _read_agent_file(self, agent_directory, relative_path):
        agent_directory = agent_directory.resolve()
        file_path = (agent_directory / relative_path).resolve()

        if agent_directory not in file_path.parents:
            raise ValueError(
                f"Agent 文件路径超出配置目录: {relative_path}"
            )
        if not file_path.is_file():
            raise FileNotFoundError(
                f"Agent 文件不存在: {file_path}"
            )

        content = file_path.read_text(encoding="utf-8").strip()
        if not content:
            raise ValueError(f"Agent 文件为空: {relative_path}")
        return content

    def _load_manifest(self, manifest_path):
        try:
            raw_manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            return AgentManifest.model_validate(raw_manifest)
        except (OSError, json.JSONDecodeError, ValidationError) as error:
            raise RuntimeError(
                f"Agent manifest 加载失败: {manifest_path}"
            ) from error

    def _load_agents(self):
        agents = {}

        for manifest_path in sorted(
            self._agents_directory.glob("*/agent.json")
        ):
            manifest = self._load_manifest(manifest_path)
            agent_directory = manifest_path.parent

            if manifest.id in agents:
                raise ValueError(
                    f"Agent ID 重复: {manifest.id}"
                )

            system_prompt = self._read_agent_file(
                agent_directory,
                manifest.system_prompt,
            )

            skills = []

            for skill_path in manifest.skills:
                skill_content = self._read_agent_file(
                    agent_directory,
                    skill_path,
                )
                skills.append(skill_content)

            agents[manifest.id] = LoadedAgent(
                id=manifest.id,
                name=manifest.name,
                description=manifest.description,
                system_prompt=system_prompt,
                skills=skills,
                tools=manifest.tools,
                permissions=manifest.permissions,
                max_turns=manifest.max_turns,
            )

        if not agents:
            raise RuntimeError(
                f"没有找到 Agent 配置: {self._agents_directory}"
            )

        return agents

    def list_agents(self):
        return list(self._agents.values())

    def get_agent(self, agent_id):
        return self._agents.get(agent_id)
