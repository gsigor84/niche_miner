import contextlib
import io
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.modules.setdefault(
    "feedparser",
    types.SimpleNamespace(FeedParserDict=dict, parse=lambda raw: types.SimpleNamespace(entries=[])),
)
sys.modules.setdefault("requests", types.SimpleNamespace(Session=lambda: types.SimpleNamespace(headers={})))
sys.modules.setdefault("bs4", types.SimpleNamespace(BeautifulSoup=lambda html, parser: types.SimpleNamespace(get_text=lambda sep, strip: "")))

import rss_miner


class RssMinerRegressionTests(unittest.TestCase):
    def test_cli_keywords_override_stale_seed_topics(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                Path("seed_topics.txt").write_text("stale keyword\n", encoding="utf-8")
                argv = [
                    "rss_miner.py",
                    "--mode",
                    "urls",
                    "--subs",
                    "testsub",
                    "--include_search",
                    "--keywords",
                    "fresh keyword",
                ]
                output = io.StringIO()
                with patch.object(sys, "argv", argv), contextlib.redirect_stdout(output):
                    rss_miner.main()

                rendered = output.getvalue()
                self.assertIn("fresh+keyword", rendered)
                self.assertNotIn("stale+keyword", rendered)
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
