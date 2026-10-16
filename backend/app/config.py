"""集中管理路径和环境配置，供 API、存储和工具执行共用。"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    database_path: Path = BACKEND_DIRECTORY / "data" / "workbench.db"
    agents_directory: Path = BACKEND_DIRECTORY / "agents"
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )

    @classmethod
    def from_env(cls):
        load_dotenv(BACKEND_DIRECTORY / ".env")
        database_path = os.getenv("WORKBENCH_DATABASE_PATH")
        agents_directory = os.getenv("WORKBENCH_AGENTS_DIRECTORY")
        origins = os.getenv("WORKBENCH_CORS_ORIGINS")
        values = {}
        if database_path:
            values["database_path"] = Path(database_path).expanduser().resolve()
        if agents_directory:
            values["agents_directory"] = Path(agents_directory).expanduser().resolve()
        if origins:
            values["cors_origins"] = tuple(origins.replace(" ", "").split(","))
        return cls(**values)
