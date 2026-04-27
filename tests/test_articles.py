import unittest

from digestor.articles import canonical_url, fingerprint


class ArticleTests(unittest.TestCase):
    def test_canonical_url_removes_tracking(self):
        url = canonical_url("HTTPS://Example.com/path/?utm_source=x&b=2&a=1#frag")
        self.assertEqual(url, "https://example.com/path?a=1&b=2")

    def test_fingerprint_normalizes_html_and_case(self):
        self.assertEqual(fingerprint("Title", "<p>Hello</p>"), fingerprint(" title ", "hello"))


if __name__ == "__main__":
    unittest.main()
