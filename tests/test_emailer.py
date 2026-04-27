import unittest

from digestor.config import Profile
from digestor.emailer import render_digest_html


class EmailerTests(unittest.TestCase):
    def test_render_digest_html(self):
        html = render_digest_html(
            Profile(name="client"),
            "2026-04-24",
            {
                "topics": [
                    {
                        "title": "AI",
                        "summary": "Summary",
                        "why_it_matters": "Important",
                        "key_points": ["Point"],
                        "source_links": [{"title": "Source", "url": "https://example.com", "source": "Example"}],
                    }
                ]
            },
        )
        self.assertIn("client: digest 2026-04-24", html)
        self.assertIn("Source", html)


if __name__ == "__main__":
    unittest.main()
