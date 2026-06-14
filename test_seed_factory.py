import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import seed_factory


class SeedFactoryTests(unittest.TestCase):
    def test_empty_generation_exits_without_overwriting_existing_seed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "seed_topics.txt"
            output_path.write_text("existing seed\n", encoding="utf-8")

            class EmptyFactory:
                def __init__(self):
                    self.output_path = output_path
                    self.seeds = set()

                def load_existing(self):
                    pass

                def harvest_google_taxonomy(self):
                    pass

                def brainstorm_llm(self, topic, count=10, model=seed_factory.DEFAULT_MODEL):
                    pass

                def save(self):
                    output_path.write_text("overwritten\n", encoding="utf-8")

            with patch.object(seed_factory, "SeedFactory", EmptyFactory):
                with patch.object(sys, "argv", ["seed_factory.py", "--source", "google"]):
                    with self.assertRaises(SystemExit) as raised:
                        seed_factory.main()

            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "existing seed\n")


if __name__ == "__main__":
    unittest.main()
