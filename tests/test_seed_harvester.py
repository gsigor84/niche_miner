import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import seed_harvester


class SeedHarvesterOutputSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.tmp_path = Path(self.tmpdir.name)
        self.output_file = self.tmp_path / "seed_topics.txt"
        self.output_file.write_text("crm tools\nsales automation\n", encoding="utf-8")

        patcher = mock.patch.object(seed_harvester, "OUTPUT_FILE", str(self.output_file))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_download_failure_preserves_existing_seeds(self):
        with mock.patch.object(
            seed_harvester.requests,
            "get",
            side_effect=RuntimeError("network down"),
        ):
            rc = seed_harvester.harvest_products()

        self.assertEqual(rc, 1)
        content = self.output_file.read_text(encoding="utf-8")
        self.assertIn("crm tools", content)
        self.assertIn("sales automation", content)

    def test_empty_taxonomy_does_not_wipe_seeds(self):
        class FakeResponse:
            text = "# Google Product Taxonomy\n\n"

            def raise_for_status(self):
                return None

        with mock.patch.object(
            seed_harvester.requests,
            "get",
            return_value=FakeResponse(),
        ):
            rc = seed_harvester.harvest_products()

        self.assertEqual(rc, 1)
        content = self.output_file.read_text(encoding="utf-8")
        self.assertIn("crm tools", content)
        self.assertIn("sales automation", content)

    def test_successful_harvest_replaces_seeds_atomically(self):
        class FakeResponse:
            text = (
                "# Google Product Taxonomy\n"
                "Animals & Pet Supplies > Pet Supplies > Bird Supplies > Bird Cages & Stands\n"
                "Apparel & Accessories > Clothing > Shirts & Tops\n"
            )

            def raise_for_status(self):
                return None

        with mock.patch.object(
            seed_harvester.requests,
            "get",
            return_value=FakeResponse(),
        ):
            rc = seed_harvester.harvest_products()

        self.assertEqual(rc, 0)
        content = self.output_file.read_text(encoding="utf-8")
        self.assertNotIn("crm tools", content)
        self.assertIn("bird cages stands", content)
        self.assertIn("shirts tops", content)

    def test_taxonomy_url_uses_https(self):
        self.assertTrue(seed_harvester.TAXONOMY_URL.startswith("https://"))


if __name__ == "__main__":
    unittest.main()
