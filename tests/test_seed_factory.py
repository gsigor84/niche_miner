import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import seed_factory


class SeedFactorySafetyTests(unittest.TestCase):
    def test_empty_generation_does_not_overwrite_existing_seed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_path = Path(tmp) / "seed_topics.txt"
            original = "# existing\ncrm tools\n"
            seed_path.write_text(original, encoding="utf-8")

            with patch.object(seed_factory, "OUTPUT_FILE", str(seed_path)), patch.object(
                seed_factory.SeedFactory, "harvest_google_taxonomy", lambda self: None
            ), patch("sys.argv", ["seed_factory.py", "--source", "google"]):
                with self.assertRaises(SystemExit) as raised:
                    seed_factory.main()

            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(seed_path.read_text(encoding="utf-8"), original)

    def test_llm_source_requires_topic_with_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_path = Path(tmp) / "seed_topics.txt"

            with patch.object(seed_factory, "OUTPUT_FILE", str(seed_path)), patch(
                "sys.argv", ["seed_factory.py", "--source", "llm"]
            ):
                with self.assertRaises(SystemExit) as raised:
                    seed_factory.main()

            self.assertEqual(raised.exception.code, 2)
            self.assertFalse(seed_path.exists())


if __name__ == "__main__":
    unittest.main()
