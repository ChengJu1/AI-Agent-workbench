"""Daily online backups of the SQLite database; the newest `keep` days are kept."""
import asyncio
import logging
import sqlite3
from datetime import date

logger = logging.getLogger(__name__)
PREFIX = "workbench-"


def backup_database(database_path, directory, keep, today=None):
    """Write today's copy if missing, using SQLite's online backup so writers are not blocked. Returns the path or None."""
    day = (today or date.today()).isoformat()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{PREFIX}{day}.db"
    if not target.exists() and database_path.exists():
        partial = target.with_suffix(".db.partial")
        source, copy = sqlite3.connect(database_path), sqlite3.connect(partial)
        try:
            with copy:
                source.backup(copy)
        finally:
            source.close()
            copy.close()
        partial.replace(target)  # A crash mid-copy never leaves a file that looks complete.
        target.chmod(0o600)
    for old in sorted(directory.glob(f"{PREFIX}*.db"))[:-keep]:
        old.unlink()
    return target if target.exists() else None


async def run_daily(database_path, directory, keep, interval_seconds=6 * 3600):
    """Checks a few times a day so a machine that sleeps overnight still gets one backup per day."""
    while True:
        try:
            await asyncio.to_thread(backup_database, database_path, directory, keep)
        except Exception:
            logger.exception("数据库备份失败: directory=%s", directory)
        await asyncio.sleep(interval_seconds)
