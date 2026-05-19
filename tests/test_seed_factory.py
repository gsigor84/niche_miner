import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import seed_factory


class SeedFactoryRegressionTests(unittest.TestCase):
    def test_llm_failure_does_not_overwrite_existing_seed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                seed_file = Path("seed_topics.txt")
                original = "# Existing seeds\nparty tickets\n"
                seed_file.write_text(original, encoding="utf-8")

                argv = ["seed_factory.py", "--source", "llm", "--topic", "tickets"]
                with patch.object(sys, "argv", argv), \
                     patch.object(seed_factory.requests, "post", side_effect=RuntimeError("llm down"), create=True):
                    self.assertEqual(seed_factory.main(), 1)

                self.assertEqual(seed_file.read_text(encoding="utf-8"), original)
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
