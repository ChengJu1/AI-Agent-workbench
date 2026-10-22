import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.backup import backup_database


class BackupTests(unittest.TestCase):
    def test_daily_copy_is_complete_once_per_day_and_old_ones_are_pruned(self):
        with tempfile.TemporaryDirectory() as folder:
            database, backups = Path(folder) / 'w.db', Path(folder) / 'backups'
            with sqlite3.connect(database) as connection:
                connection.execute('CREATE TABLE notes(text TEXT)')
                connection.execute("INSERT INTO notes VALUES ('合成')")
            for day in range(1, 10):
                backup_database(database, backups, keep=3, today=date(2026, 10, day))
            kept = sorted(p.name for p in backups.iterdir())
            self.assertEqual(kept, ['workbench-2026-10-07.db', 'workbench-2026-10-08.db', 'workbench-2026-10-09.db'])
            with sqlite3.connect(backups / kept[-1]) as copy:
                self.assertEqual(copy.execute('SELECT text FROM notes').fetchall(), [('合成',)])
            # A second run on the same day leaves the existing copy alone.
            with sqlite3.connect(database) as connection:
                connection.execute("INSERT INTO notes VALUES ('之后')")
            backup_database(database, backups, keep=3, today=date(2026, 10, 9))
            with sqlite3.connect(backups / kept[-1]) as copy:
                self.assertEqual(len(copy.execute('SELECT text FROM notes').fetchall()), 1)
            self.assertEqual((backups / kept[-1]).stat().st_mode & 0o777, 0o600)


if __name__ == '__main__':
    unittest.main()
