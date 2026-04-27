import unittest
from pathlib import Path

from digestor.feeds import parse_feed


class FeedTests(unittest.TestCase):
    def test_parse_rss_feed(self):
        xml = Path("tests/fixtures/sample_feed.xml").read_text(encoding="utf-8")
        articles = parse_feed(xml, source_url="https://example.com/feed.xml")
        self.assertEqual(len(articles), 2)
        self.assertEqual(articles[0].source, "Editorial Tech")
        self.assertIn("AI tools", articles[0].title)
        self.assertTrue(articles[0].published_at.startswith("2026-04-24"))


if __name__ == "__main__":
    unittest.main()
