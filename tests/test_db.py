from datetime import date
from pathlib import Path
import tempfile
import unittest

from digestor.articles import Article
from digestor.db import candidate_articles, connect, mark_digest_sent, store_digest, upsert_article


class DatabaseTests(unittest.TestCase):
    def test_sent_digest_marks_articles_out_of_future_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = connect(Path(tmp) / "digest.sqlite")
            article_id, inserted = upsert_article(
                conn,
                "client",
                Article(
                    url="https://example.com/a",
                    title="AI in publishing",
                    published_at="2026-04-24T08:00:00+00:00",
                    summary="AI tools change editorial work.",
                ),
            )
            self.assertTrue(inserted)
            self.assertEqual(len(candidate_articles(conn, "client", date(2026, 4, 24), 10)), 1)

            digest_id = store_digest(
                conn,
                "client",
                date(2026, 4, 24),
                "client digest",
                Path(tmp) / "digest.html",
                {"topics": [{"title": "AI", "article_ids": [article_id]}]},
                [article_id],
            )
            mark_digest_sent(conn, digest_id)
            self.assertEqual(candidate_articles(conn, "client", date(2026, 4, 25), 10), [])


if __name__ == "__main__":
    unittest.main()
