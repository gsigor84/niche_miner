import importlib
import sys
import types
import unittest


def install_optional_dependency_stubs():
    feedparser = types.ModuleType("feedparser")
    feedparser.FeedParserDict = dict
    feedparser.parse = lambda raw: types.SimpleNamespace(entries=[])
    sys.modules.setdefault("feedparser", feedparser)

    class BeautifulSoup:
        def __init__(self, html, parser):
            self.html = html or ""

        def get_text(self, separator, strip):
            text = str(self.html)
            return text.strip() if strip else text

    bs4 = types.ModuleType("bs4")
    bs4.BeautifulSoup = BeautifulSoup
    sys.modules.setdefault("bs4", bs4)

    class FakeSession:
        def __init__(self):
            self.headers = {}

    requests = types.ModuleType("requests")
    requests.Session = FakeSession
    sys.modules.setdefault("requests", requests)


install_optional_dependency_stubs()
rss_miner = importlib.import_module("rss_miner")


class RssMinerKeywordTests(unittest.TestCase):
    def test_parse_keywords_accepts_cli_keywords_without_seed_file(self):
        self.assertEqual(
            rss_miner.parse_keywords("crm software, sales automation"),
            ["crm software", "sales automation"],
        )

    def test_parse_keywords_applies_prefix_like_seed_file_loading(self):
        self.assertEqual(
            rss_miner.parse_keywords("crm software,best sales automation", prefix="best"),
            ["best crm software", "best sales automation"],
        )


if __name__ == "__main__":
    unittest.main()
