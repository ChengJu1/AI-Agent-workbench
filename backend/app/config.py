"""集中管理路径和环境配置，供 API、存储和工具执行共用。"""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
DEFAULT_SKILL_READ_BUDGET_CHARS = 80000


@dataclass(frozen=True)
class Settings:
    database_path: Path = BACKEND_DIRECTORY / "data" / "workbench.db"
    agents_directory: Path = BACKEND_DIRECTORY / "agents"
    skill_read_budget_chars: int = DEFAULT_SKILL_READ_BUDGET_CHARS
    deepagents_enabled: bool = False
    deepagents_model: str = 'deepseek-v4-pro'
    deepagents_base_url: str = 'https://api.deepseek.com'
    deepagents_api_key: str = field(default='', repr=False)
    deepagents_checkpoint_path: Path | None = None
    deepagents_artifacts_directory: Path | None = None
    claude_result_offload_enabled: bool = False
    tool_result_offload_chars: int = 4000
    deepagents_summary_trigger_tokens: int = 32000
    deepagents_summary_trigger_messages: int = 80
    deepagents_summary_keep_messages: int = 12
    trusted_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "testserver", "backend")
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )

    def __post_init__(self):
        if Path(self.checkpoint_path).resolve() == Path(self.database_path).resolve():
            raise ValueError('Deep Agents 状态存档必须使用独立数据库文件')
        if type(self.deepagents_enabled) is not bool:
            raise ValueError('WORKBENCH_DEEPAGENTS_ENABLED 必须是布尔值')
        if type(self.skill_read_budget_chars) is not int or self.skill_read_budget_chars < 1:
            raise ValueError("WORKBENCH_SKILL_READ_BUDGET_CHARS 必须是正整数")
        if type(self.claude_result_offload_enabled) is not bool:
            raise ValueError('WORKBENCH_CLAUDE_RESULT_OFFLOAD_ENABLED 必须是布尔值')
        for name in ('tool_result_offload_chars', 'deepagents_summary_trigger_tokens',
                     'deepagents_summary_trigger_messages', 'deepagents_summary_keep_messages'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(name + ' 必须是正整数')
        if self.deepagents_summary_keep_messages >= self.deepagents_summary_trigger_messages:
            raise ValueError('摘要保留条数必须小于触发条数')

    @property
    def checkpoint_path(self):
        database = Path(self.database_path)
        filename = 'deepagents-state.db' if database.name == 'deepagents.db' else 'deepagents.db'
        return self.deepagents_checkpoint_path or database.parent / filename

    @property
    def artifacts_directory(self):
        return self.deepagents_artifacts_directory or Path(self.database_path).parent / 'runtime-artifacts'

    @classmethod
    def from_env(cls):
        load_dotenv(BACKEND_DIRECTORY / ".env")
        database_path = os.getenv("WORKBENCH_DATABASE_PATH")
        agents_directory = os.getenv("WORKBENCH_AGENTS_DIRECTORY")
        origins = os.getenv("WORKBENCH_CORS_ORIGINS")
        hosts = os.getenv("WORKBENCH_TRUSTED_HOSTS")
        values = {}
        if database_path:
            values["database_path"] = Path(database_path).expanduser().resolve()
        if agents_directory:
            values["agents_directory"] = Path(agents_directory).expanduser().resolve()
        if origins:
            values["cors_origins"] = tuple(origins.replace(" ", "").split(","))
        if hosts:
            values["trusted_hosts"] = tuple(item.strip() for item in hosts.split(",") if item.strip())
        budget = os.getenv("WORKBENCH_SKILL_READ_BUDGET_CHARS")
        if budget is not None:
            values["skill_read_budget_chars"] = int(budget)
        enabled = os.getenv('WORKBENCH_DEEPAGENTS_ENABLED', 'false').lower()
        if enabled not in ('true', 'false'):
            raise ValueError('WORKBENCH_DEEPAGENTS_ENABLED 必须为 true 或 false')
        values['deepagents_enabled'] = enabled == 'true'
        offload = os.getenv('WORKBENCH_CLAUDE_RESULT_OFFLOAD_ENABLED', 'false').lower()
        if offload not in ('true', 'false'):
            raise ValueError('WORKBENCH_CLAUDE_RESULT_OFFLOAD_ENABLED 必须为 true 或 false')
        values['claude_result_offload_enabled'] = offload == 'true'
        for name in ('tool_result_offload_chars', 'deepagents_summary_trigger_tokens',
                     'deepagents_summary_trigger_messages', 'deepagents_summary_keep_messages'):
            value = os.getenv('WORKBENCH_' + name.upper())
            if value is not None:
                values[name] = int(value)
        for name in ('model', 'base_url', 'api_key'):
            value = os.getenv('WORKBENCH_DEEPAGENTS_' + name.upper())
            if value is not None:
                values['deepagents_' + name] = value
        for name in ('checkpoint_path', 'artifacts_directory'):
            value = os.getenv('WORKBENCH_DEEPAGENTS_' + name.upper())
            if value:
                values['deepagents_' + name] = Path(value).expanduser().resolve()
        return cls(**values)
