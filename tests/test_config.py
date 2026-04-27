import unittest

from digestor.config import _minimal_yaml_load, profile_from_mapping


class ConfigTests(unittest.TestCase):
    def test_minimal_yaml_profile(self):
        data = _minimal_yaml_load(
            """
            language: it
            max_articles: 25
            include_keywords:
              - AI
              - editoria
            feeds:
              - url: https://example.com/feed.xml
                title: Example
                weight: 2
            """
        )
        profile = profile_from_mapping("client", data)
        self.assertEqual(profile.language, "it")
        self.assertEqual(profile.max_articles, 25)
        self.assertEqual(profile.include_keywords, ["AI", "editoria"])
        self.assertEqual(profile.feeds[0].weight, 2)


if __name__ == "__main__":
    unittest.main()
