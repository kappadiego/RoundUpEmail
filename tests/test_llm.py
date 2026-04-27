import unittest

from digestor.config import Profile
from digestor.llm import offline_digest


class LLMTests(unittest.TestCase):
    def test_offline_digest_groups_by_keyword(self):
        payload = offline_digest(
            Profile(name="client", include_keywords=["AI"]),
            [
                {
                    "id": 1,
                    "title": "AI in publishing",
                    "summary": "AI changes publishing",
                    "content": "",
                    "url": "https://example.com/a",
                    "source": "Example",
                }
            ],
        )
        self.assertEqual(payload["topics"][0]["title"], "Ai")
        self.assertEqual(payload["topics"][0]["article_ids"], [1])


if __name__ == "__main__":
    unittest.main()
