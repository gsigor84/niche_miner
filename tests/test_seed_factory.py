import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import seed_factory


class SeedFactoryTests(unittest.TestCase):
    def test_failed_generation_does_not_overwrite_existing_seed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_path = Path(tmp) / "seed_topics.txt"
            original = "# existing\ncrm software\n"
            seed_path.write_text(original, encoding="utf-8")

            class EmptySeedFactory(seed_factory.SeedFactory):
                def __init__(self):
                    super().__init__(output_path=str(seed_path))

                def harvest_google_taxonomy(self):
                    return None

            with patch("sys.argv", ["seed_factory.py", "--source", "google"]), \
                 patch.object(seed_factory, "SeedFactory", EmptySeedFactory):
                with self.assertRaises(SystemExit) as raised:
                    seed_factory.main()

            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(seed_path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
