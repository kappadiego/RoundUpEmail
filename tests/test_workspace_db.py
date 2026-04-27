from pathlib import Path
import tempfile
import unittest

from digestor.db import add_feed, connect, create_workspace, list_feeds, list_workspaces, workspace_profile


class WorkspaceDatabaseTests(unittest.TestCase):
    def test_workspace_and_feeds_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "digest.sqlite")
            create_workspace(conn, "editoria", "Editoria", include_keywords=["AI", "policy"], digest_time="08:30")
            feed_id = add_feed(conn, "editoria", "https://example.com/feed.xml", "Example", 2)

            self.assertGreater(feed_id, 0)
            self.assertEqual(list_workspaces(conn)[0]["slug"], "editoria")
            self.assertEqual(list_feeds(conn, "editoria")[0]["title"], "Example")

            profile = workspace_profile(conn, "editoria")
            self.assertEqual(profile.include_keywords, ["AI", "policy"])
            self.assertEqual(profile.digest_time, "08:30")
            self.assertEqual(profile.feeds[0].weight, 2)


if __name__ == "__main__":
    unittest.main()
