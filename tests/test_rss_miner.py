import sys
import types
import unittest
import importlib.util
from unittest import mock

if importlib.util.find_spec("feedparser") is None:
    sys.modules["feedparser"] = types.SimpleNamespace(parse=lambda raw: None)
if importlib.util.find_spec("requests") is None:
    sys.modules["requests"] = types.SimpleNamespace(
        Session=lambda: types.SimpleNamespace(headers={})
    )
if importlib.util.find_spec("bs4") is None:
    sys.modules["bs4"] = types.SimpleNamespace(BeautifulSoup=lambda html, parser: None)

import rss_miner


class RssMinerTests(unittest.TestCase):
    def test_cli_keywords_override_seed_file_and_keep_prefix(self):
        captured = {}

        def fake_generate_all_feed_urls(**kwargs):
            captured.update(kwargs)
            return []

        argv = [
            "rss_miner.py",
            "--mode", "urls",
            "--keywords", "alpha,beta",
            "--prefix", "best",
            "--subs", "testsub",
            "--include_search",
        ]

        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(rss_miner, "load_keywords", side_effect=AssertionError("seed file should not be read")), \
                mock.patch.object(rss_miner, "load_query_templates", return_value=["{kw} help"]), \
                mock.patch.object(rss_miner, "generate_all_feed_urls", side_effect=fake_generate_all_feed_urls):
            rss_miner.main()

        self.assertEqual(captured["keywords"], ["best alpha", "best beta"])
        self.assertEqual(captured["subs"], ["testsub"])


if __name__ == "__main__":
    unittest.main()
