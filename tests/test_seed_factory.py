import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import seed_factory


class SeedFactoryTest(unittest.TestCase):
    def test_failed_llm_generation_does_not_overwrite_existing_seed_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = Path.cwd()
            seed_path = Path(tmpdir) / "seed_topics.txt"
            seed_path.write_text("existing seed\n", encoding="utf-8")
            os.chdir(tmpdir)
            try:
                argv = ["seed_factory.py", "--source", "llm", "--topic", "party tickets"]
                with mock.patch.object(sys, "argv", argv), mock.patch.object(
                    seed_factory.requests,
                    "post",
                    side_effect=RuntimeError("ollama unavailable"),
                ):
                    with self.assertRaises(SystemExit) as raised:
                        seed_factory.main()
            finally:
                os.chdir(original_cwd)
            contents = seed_path.read_text(encoding="utf-8")

        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(contents, "existing seed\n")

    def test_missing_llm_topic_exits_nonzero_without_writing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = Path.cwd()
            seed_path = Path(tmpdir) / "seed_topics.txt"
            os.chdir(tmpdir)
            try:
                argv = ["seed_factory.py", "--source", "llm"]
                with mock.patch.object(sys, "argv", argv):
                    with self.assertRaises(SystemExit) as raised:
                        seed_factory.main()
            finally:
                os.chdir(original_cwd)
            seed_exists = seed_path.exists()

        self.assertEqual(raised.exception.code, 2)
        self.assertFalse(seed_exists)


if __name__ == "__main__":
    unittest.main()
