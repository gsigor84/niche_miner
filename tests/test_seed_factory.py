import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import seed_factory


class SeedFactorySafetyTests(unittest.TestCase):
    def run_in_tempdir(self, argv, body):
        original_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.chdir(tmpdir)
            try:
                return body(Path(tmpdir), argv)
            finally:
                os.chdir(original_cwd)

    def test_default_manual_source_does_not_overwrite_existing_seed_file(self):
        def body(tmpdir, argv):
            seed_file = tmpdir / "seed_topics.txt"
            seed_file.write_text("existing topic\n", encoding="utf-8")

            with mock.patch.object(sys, "argv", argv):
                result = seed_factory.main()

            self.assertEqual(result, 1)
            self.assertEqual(seed_file.read_text(encoding="utf-8"), "existing topic\n")

        self.run_in_tempdir(["seed_factory.py"], body)

    def test_failed_google_generation_does_not_overwrite_existing_seed_file(self):
        def body(tmpdir, argv):
            seed_file = tmpdir / "seed_topics.txt"
            seed_file.write_text("existing topic\n", encoding="utf-8")

            with mock.patch.object(sys, "argv", argv), \
                 mock.patch.object(seed_factory.SeedFactory, "harvest_google_taxonomy", return_value=None):
                result = seed_factory.main()

            self.assertEqual(result, 1)
            self.assertEqual(seed_file.read_text(encoding="utf-8"), "existing topic\n")

        self.run_in_tempdir(["seed_factory.py", "--source", "google"], body)

    def test_llm_source_requires_topic_without_overwriting(self):
        def body(tmpdir, argv):
            seed_file = tmpdir / "seed_topics.txt"
            seed_file.write_text("existing topic\n", encoding="utf-8")

            with mock.patch.object(sys, "argv", argv):
                result = seed_factory.main()

            self.assertEqual(result, 1)
            self.assertEqual(seed_file.read_text(encoding="utf-8"), "existing topic\n")

        self.run_in_tempdir(["seed_factory.py", "--source", "llm"], body)


if __name__ == "__main__":
    unittest.main()
