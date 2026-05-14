import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import seed_factory


class SeedFactoryTests(unittest.TestCase):
    def run_in_tempdir(self, argv, requests_patch):
        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                seed_file = Path("seed_topics.txt")
                seed_file.write_text("valuable seed\n", encoding="utf-8")
                with patch.object(sys, "argv", argv), requests_patch:
                    with self.assertRaises(SystemExit) as cm:
                        seed_factory.main()
                return cm.exception.code, seed_file.read_text(encoding="utf-8")
            finally:
                os.chdir(old_cwd)

    def test_google_failure_does_not_overwrite_existing_seeds(self):
        code, contents = self.run_in_tempdir(
            ["seed_factory.py", "--source", "google"],
            patch.object(seed_factory.requests, "get", side_effect=RuntimeError("offline")),
        )

        self.assertEqual(code, 1)
        self.assertEqual(contents, "valuable seed\n")

    def test_empty_llm_result_does_not_overwrite_existing_seeds(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"response": "[]"}

        code, contents = self.run_in_tempdir(
            ["seed_factory.py", "--source", "llm", "--topic", "crm"],
            patch.object(seed_factory.requests, "post", return_value=response),
        )

        self.assertEqual(code, 1)
        self.assertEqual(contents, "valuable seed\n")


if __name__ == "__main__":
    unittest.main()
