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
    # Platform defaults. The native model-aware default for a 1M-token window triggers at
    # ~850k tokens, which leaves compaction effectively off; all three None selects it.
    deepagents_summary_trigger_tokens: int | None = 32000
    deepagents_summary_trigger_messages: int | None = 80
    deepagents_summary_keep_messages: int | None = 12
    claude_auto_compact_window_tokens: int | None = None
    claude_auto_compact_pct: int | None = None
    trusted_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "testserver", "backend")
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    backup_keep: int = 7  # Days of daily database copies; 0 turns backups off.
    backup_directory: Path | None = None  # Defaults to a "backups" folder next to the database.
    access_token: str = ""  # Optional; mandatory once trusted_hosts includes a non-local host.

    def __post_init__(self):
        if Path(self.checkpoint_path).resolve() == Path(self.database_path).resolve():
            raise ValueError('Deep Agents 状态存档必须使用独立数据库文件')
        if type(self.deepagents_enabled) is not bool:
            raise ValueError('WORKBENCH_DEEPAGENTS_ENABLED 必须是布尔值')
        if type(self.skill_read_budget_chars) is not int or self.skill_read_budget_chars < 1:
            raise ValueError("WORKBENCH_SKILL_READ_BUDGET_CHARS 必须是正整数")
        if type(self.backup_keep) is not int or self.backup_keep < 0:
            raise ValueError("WORKBENCH_BACKUP_KEEP 必须是非负整数")
        if type(self.claude_result_offload_enabled) is not bool:
            raise ValueError('WORKBENCH_CLAUDE_RESULT_OFFLOAD_ENABLED 必须是布尔值')
        for name in ('tool_result_offload_chars', 'deepagents_summary_trigger_tokens',
                     'deepagents_summary_trigger_messages', 'deepagents_summary_keep_messages'):
            if name != 'tool_result_offload_chars' and getattr(self, name) is None:
                continue
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(name + ' 必须是正整数')
        if self.deepagents_summary_keep_messages is not None and self.deepagents_summary_trigger_messages is not None and self.deepagents_summary_keep_messages >= self.deepagents_summary_trigger_messages:
            raise ValueError('摘要保留条数必须小于触发条数')
        if self.deepagents_summary_keep_messages is None and (
                self.deepagents_summary_trigger_tokens is not None or self.deepagents_summary_trigger_messages is not None):
            # The native keep (10% of the window) can exceed an explicit trigger, so compaction would keep everything.
            raise ValueError('设置摘要触发阈值时必须同时设置保留条数；三项都设为 auto 才使用框架默认')
        for name, low, high in [('claude_auto_compact_window_tokens', 100000, 1000000), ('claude_auto_compact_pct', 1, 100)]:
            value = getattr(self, name)
            if value is not None and (type(value) is not int or not low <= value <= high):
                raise ValueError(f'{name} 必须为 {low}–{high} 的整数')

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
        if token := os.getenv("WORKBENCH_ACCESS_TOKEN", "").strip():
            values["access_token"] = token
        if (keep := os.getenv("WORKBENCH_BACKUP_KEEP")) is not None:
            values["backup_keep"] = int(keep)
        if backup_directory := os.getenv("WORKBENCH_BACKUP_DIRECTORY"):
            values["backup_directory"] = Path(backup_directory).expanduser().resolve()
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
                     'deepagents_summary_trigger_messages', 'deepagents_summary_keep_messages',
                     'claude_auto_compact_window_tokens', 'claude_auto_compact_pct'):
            value = os.getenv('WORKBENCH_' + name.upper())
            if value is not None:
                values[name] = None if name.startswith('deepagents_summary_') and value.lower() == 'auto' else int(value)
        for name in ('model', 'base_url', 'api_key'):
            value = os.getenv('WORKBENCH_DEEPAGENTS_' + name.upper())
            if value is not None:
                values['deepagents_' + name] = value
        for name in ('checkpoint_path', 'artifacts_directory'):
            value = os.getenv('WORKBENCH_DEEPAGENTS_' + name.upper())
            if value:
                values['deepagents_' + name] = Path(value).expanduser().resolve()
        return cls(**values)
