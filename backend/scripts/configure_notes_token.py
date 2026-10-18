"""生成本机笔记 MCP 密钥，可同步当前数据库中指向本机服务的 Agent。"""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
from urllib.parse import urlsplit

from dotenv import dotenv_values, set_key

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import BACKEND_DIRECTORY


def is_local_notes(tool, port):
    if tool.get("type") != "mcp" or tool.get("transport") != "http":
        return False
    url = urlsplit(tool.get("url", ""))
    host = (url.hostname or "").lower()
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host in {"localhost", "notes-mcp", "host.docker.internal"}
    return (local and url.scheme == "http" and (url.port or 80) == port and url.path.rstrip("/") == "/mcp"
            and bool({"search_notes", "read_note", "list_notes", "list_note_collections"}.intersection(tool.get("actions", []))))


def configure(env_path, database_path, token_path, sync_agents=False, port=8059):
    values = dotenv_values(env_path) if env_path.exists() else {}
    token = values.get("NOTES_MCP_TOKEN") or secrets.token_urlsafe(32)
    if len(token) < 32 or not token.isascii() or any(char.isspace() for char in token):
        raise ValueError("现有 NOTES_MCP_TOKEN 格式无效，请先更正；脚本不会自动覆盖现有密钥。")
    env_path.parent.mkdir(parents=True, exist_ok=True)
    set_key(env_path, "NOTES_MCP_TOKEN", token)
    os.chmod(env_path, 0o600)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    # 拒绝符号链接，避免将密钥写入意外的目标；创建时即限制权限。
    descriptor = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write(token + "\n")
    updated = 0
    if sync_agents and database_path.is_file():
        with sqlite3.connect(database_path.resolve().as_uri() + "?mode=rw", uri=True) as connection:
            connection.execute("BEGIN IMMEDIATE")
            for agent_id, definition in connection.execute("SELECT id, definition FROM custom_agents").fetchall():
                agent = json.loads(definition)
                changed = False
                for tool in agent.get("tools", []):
                    if is_local_notes(tool, port):
                        headers = {key: value for key, value in tool.get("headers", {}).items() if key.lower() != "authorization"}
                        headers["Authorization"] = f"Bearer {token}"
                        tool["headers"] = headers
                        changed = True
                if changed:
                    connection.execute("UPDATE custom_agents SET definition = ? WHERE id = ?", (json.dumps(agent, ensure_ascii=False), agent_id))
                    updated += 1
    return updated


def main():
    parser = argparse.ArgumentParser(description="配置笔记 MCP 令牌（不会输出令牌内容）")
    parser.add_argument("--sync-agents", action="store_true", help="同步指向本机笔记服务的已有 Agent 认证请求头")
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--port", type=int, default=8059)
    args = parser.parse_args()
    env_path = BACKEND_DIRECTORY / ".env"
    values = dotenv_values(env_path)
    database_path = args.database or Path(values.get("WORKBENCH_DATABASE_PATH") or BACKEND_DIRECTORY / "data/workbench.db").expanduser()
    token_path = BACKEND_DIRECTORY / "data/notes-mcp-token.txt"
    updated = configure(env_path, database_path, token_path, args.sync_agents, args.port)
    print(f"令牌已保存到 {token_path}（仅当前用户可读），已同步 {updated} 个 Agent。重启笔记 MCP 服务后生效。")


if __name__ == "__main__":
    main()
