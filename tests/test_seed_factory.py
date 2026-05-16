import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import seed_factory


class SeedFactoryTests(unittest.TestCase):
    def test_llm_failure_does_not_overwrite_existing_seed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            seed_path = Path(tmp) / "seed_topics.txt"
            seed_path.write_text("existing seed\n", encoding="utf-8")

            try:
                os.chdir(tmp)
                argv = [
                    "seed_factory.py",
                    "--source", "llm",
                    "--topic", "crm software",
                ]
                with mock.patch.object(sys, "argv", argv), \
                        mock.patch.object(seed_factory.requests, "post", side_effect=RuntimeError("ollama down")):
                    exit_code = seed_factory.main()
                seed_contents = seed_path.read_text(encoding="utf-8")
            finally:
                os.chdir(old_cwd)

        self.assertEqual(exit_code, 1)
        self.assertEqual(seed_contents, "existing seed\n")

    def test_empty_seed_set_is_not_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_path = Path(tmp) / "seed_topics.txt"
            seed_path.write_text("existing seed\n", encoding="utf-8")

            factory = seed_factory.SeedFactory(str(seed_path))

            self.assertFalse(factory.save())
            self.assertEqual(seed_path.read_text(encoding="utf-8"), "existing seed\n")


if __name__ == "__main__":
    unittest.main()
