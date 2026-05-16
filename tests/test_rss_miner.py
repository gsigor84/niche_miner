import io
import sys
import types
import unittest
from unittest import mock

feedparser_stub = types.ModuleType("feedparser")
feedparser_stub.parse = lambda raw: None
sys.modules.setdefault("feedparser", feedparser_stub)

bs4_stub = types.ModuleType("bs4")
bs4_stub.BeautifulSoup = lambda *args, **kwargs: None
sys.modules.setdefault("bs4", bs4_stub)

import rss_miner


class RssMinerTests(unittest.TestCase):
    def test_cli_keywords_override_seed_file_for_url_generation(self):
        argv = [
            "rss_miner.py",
            "--mode", "urls",
            "--niche_type", "saas",
            "--subs", "CRMSoftware",
            "--keywords", "crm tools",
            "--include_search",
        ]

        with mock.patch.object(sys, "argv", argv), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            rss_miner.main()

        output = stdout.getvalue()
        self.assertIn("best+crm+tools+software", output)
        self.assertNotIn("ai+agents", output)


if __name__ == "__main__":
    unittest.main()
