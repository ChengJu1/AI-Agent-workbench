# 从 backend/agents 读取并校验 Agent 配置、Prompt 和 Skill 文件。
# 加载完成的 Agent 会保存在内存中供后端查询。
import json
from pathlib import Path

from pydantic import ValidationError

from app.agent_manifest import AgentManifest, LoadedAgent


class AgentRegistry:
    def __init__(self, agents_directory=None):
        self._agents_directory = agents_directory or (
            Path(__file__).resolve().parents[2] / "agents"
        )
        self._agents = self._load_agents()

    def _read_agent_file(self, agent_directory, relative_path):# 接收agent列表路径和相对的agent.json路径 然后拼接读取 返回python字符串
        agent_directory = agent_directory.resolve() #拿到绝对路径，这里的绝对路径是agents文件夹的路径（agent_dirctory由输入决定）
        file_path = (agent_directory / relative_path).resolve() # 再通过相对路径拿到具体要用哪个agent

        if agent_directory not in file_path.parents: # 因为relative_path来自可以修改的agent.json 比如恶意修改为/../../../.env 就有可能读取到环境信息
            raise ValueError(
                f"Agent 文件路径超出配置目录: {relative_path}"
            )
        """
        1. 路径存在
        2. 路径指向的是文件，不是文件夹
        """
        if not file_path.is_file(): # not(真实存在 而且是文件)
            raise FileNotFoundError(
                f"Agent 文件不存在: {file_path}"
            )

        return file_path.read_text(encoding="utf-8").strip() # 去开头结尾空白字符 然后读取

    def _load_manifest(self, manifest_path): # 获取一个输入的清单路径 然后输出经过审批后的清单内容清单内容
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
        ): # 找agent_directory下面每一个符合条件的文件
            manifest = self._load_manifest(manifest_path)
            agent_directory = manifest_path.parent # 找到存放agent的文件夹

            if manifest.id in agents: # 读取agent.json得到manifest之后，如果出现了重复agent，前一个就会覆盖后一个 所以要避免
               raise ValueError(
                    f"Agent ID 重复: {manifest.id}"
                )

            system_prompt = self._read_agent_file( # 拿到提示词
                agent_directory,
                manifest.system_prompt,
            )

            skills = []

            for skill_path in manifest.skills: # 读取skill
                skill_content = self._read_agent_file(
                    agent_directory,
                    skill_path,
                )
                skills.append(skill_content)

            agents[manifest.id] = LoadedAgent( # 登记agent
                id=manifest.id,
                name=manifest.name,
                description=manifest.description,
                system_prompt=system_prompt,
                skills=skills,
                tools=manifest.tools,
                permissions=manifest.permissions,
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
