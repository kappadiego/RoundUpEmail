import importlib.util
import unittest


@unittest.skipIf(importlib.util.find_spec("fastapi") is None, "FastAPI is not installed")
class WebImportTests(unittest.TestCase):
    def test_web_app_imports(self):
        from digestor.web import app

        self.assertEqual(app.title, "RoundUpEmail")


if __name__ == "__main__":
    unittest.main()
