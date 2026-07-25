import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import trash_miner


class TrashMinerOutputSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.tmp_path = Path(self.tmpdir.name)
        self.seed_file = self.tmp_path / "seed_topics.txt"
        self.output_file = self.tmp_path / "suggested_trash_candidates.txt"
        self.seed_file.write_text("crm tools\nsales automation\n", encoding="utf-8")
        self.output_file.write_text(
            "# PRIOR CANDIDATES\nimportant\t(42)\n",
            encoding="utf-8",
        )

        patchers = [
            mock.patch.object(trash_miner, "SEED_FILE", str(self.seed_file)),
            mock.patch.object(trash_miner, "OUTPUT_FILE", str(self.output_file)),
            mock.patch.object(trash_miner.time, "sleep", lambda _seconds: None),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_total_autocomplete_outage_preserves_existing_report(self):
        with mock.patch.object(trash_miner, "get_autocomplete", return_value=None):
            rc = trash_miner.mine_trash()

        self.assertEqual(rc, 1)
        content = self.output_file.read_text(encoding="utf-8")
        self.assertIn("PRIOR CANDIDATES", content)
        self.assertIn("important\t(42)", content)

    def test_empty_suggestions_do_not_truncate_report(self):
        with mock.patch.object(trash_miner, "get_autocomplete", return_value=[]):
            rc = trash_miner.mine_trash()

        self.assertEqual(rc, 1)
        content = self.output_file.read_text(encoding="utf-8")
        self.assertIn("PRIOR CANDIDATES", content)

    def test_successful_mine_replaces_report_atomically(self):
        def fake_autocomplete(query):
            return [f"{query} pricing", f"{query} alternative"]

        with mock.patch.object(trash_miner, "get_autocomplete", side_effect=fake_autocomplete):
            rc = trash_miner.mine_trash()

        self.assertEqual(rc, 0)
        content = self.output_file.read_text(encoding="utf-8")
        self.assertNotIn("PRIOR CANDIDATES", content)
        self.assertIn("pricing", content)
        self.assertIn("alternative", content)

    def test_autocomplete_url_encodes_query_and_uses_https(self):
        captured = {}

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return ["crm tools", ["crm tools pricing"], [], []]

        def fake_get(url, timeout=5):
            captured["url"] = url
            captured["timeout"] = timeout
            return FakeResponse()

        with mock.patch.object(trash_miner.requests, "get", side_effect=fake_get):
            suggestions = trash_miner.get_autocomplete("crm tools")

        self.assertEqual(suggestions, ["crm tools pricing"])
        self.assertTrue(captured["url"].startswith("https://suggestqueries.google.com/"))
        self.assertIn("q=crm+tools", captured["url"])


if __name__ == "__main__":
    unittest.main()
