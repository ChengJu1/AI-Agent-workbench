"""集中管理路径和环境配置，供 API、存储和工具执行共用。"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]
DEFAULT_SKILL_READ_BUDGET_CHARS = 80000


@dataclass(frozen=True)
class Settings:
    database_path: Path = BACKEND_DIRECTORY / "data" / "workbench.db"
    agents_directory: Path = BACKEND_DIRECTORY / "agents"
    skill_read_budget_chars: int = DEFAULT_SKILL_READ_BUDGET_CHARS
    trusted_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "testserver", "backend")
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )
    backup_keep: int = 7  # Days of daily database copies; 0 turns backups off.
    backup_directory: Path | None = None  # Defaults to a "backups" folder next to the database.

    def __post_init__(self):
        if type(self.skill_read_budget_chars) is not int or self.skill_read_budget_chars < 1:
            raise ValueError("WORKBENCH_SKILL_READ_BUDGET_CHARS 必须是正整数")
        if type(self.backup_keep) is not int or self.backup_keep < 0:
            raise ValueError("WORKBENCH_BACKUP_KEEP 必须是非负整数")

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
        if (keep := os.getenv("WORKBENCH_BACKUP_KEEP")) is not None:
            values["backup_keep"] = int(keep)
        if backup_directory := os.getenv("WORKBENCH_BACKUP_DIRECTORY"):
            values["backup_directory"] = Path(backup_directory).expanduser().resolve()
        budget = os.getenv("WORKBENCH_SKILL_READ_BUDGET_CHARS")
        if budget is not None:
            values["skill_read_budget_chars"] = int(budget)
        return cls(**values)
