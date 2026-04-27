from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from digestor.db import connect, create_workspace, latest_digest, mark_digest_sent, store_digest
from digestor.scheduler import DigestScheduler


class SchedulerTests(unittest.TestCase):
    def test_digest_due_after_digest_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "digest.sqlite"
            conn = connect(db_path)
            create_workspace(conn, "client", "Client", digest_time="08:00")
            workspace = conn.execute("SELECT * FROM workspaces WHERE slug = 'client'").fetchone()
            scheduler = DigestScheduler(str(db_path))

            self.assertTrue(scheduler._digest_due(conn, workspace, datetime(2026, 4, 24, 8, 1)))
            digest_id = store_digest(conn, "client", datetime(2026, 4, 24).date(), "subject", Path(tmp) / "d.html", {"topics": []}, [])
            mark_digest_sent(conn, digest_id)
            self.assertFalse(scheduler._digest_due(conn, workspace, datetime(2026, 4, 24, 8, 2)))
            self.assertIsNotNone(latest_digest(conn, "client", datetime(2026, 4, 24).date()))


if __name__ == "__main__":
    unittest.main()
