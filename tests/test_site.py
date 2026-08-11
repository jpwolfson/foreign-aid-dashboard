import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SiteDataLoadingTests(unittest.TestCase):
    def test_json_fetches_are_schema_versioned_and_bypass_browser_cache(self):
        html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")

        self.assertIn('const DATA_SCHEMA_VERSION = "award-transactions-v1";', html)
        self.assertIn('dashboard.json?v=${DATA_SCHEMA_VERSION}', html)
        self.assertIn('awards.json?v=${DATA_SCHEMA_VERSION}', html)
        self.assertEqual(html.count('{cache:"no-store"}'), 2)


if __name__ == "__main__":
    unittest.main()
