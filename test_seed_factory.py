import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import seed_factory


class SeedFactoryMainTests(unittest.TestCase):
    def test_default_manual_source_refuses_empty_overwrite(self):
        with patch("sys.argv", ["seed_factory.py"]), \
                patch("seed_factory.SeedFactory.save") as save:
            with redirect_stdout(io.StringIO()) as stdout:
                result = seed_factory.main()

        self.assertEqual(result, 1)
        save.assert_not_called()
        self.assertIn("refusing to overwrite", stdout.getvalue())

    def test_google_source_saves_when_seeds_generated(self):
        def add_seed(self):
            self.seeds.add("crm software")

        with patch("sys.argv", ["seed_factory.py", "--source", "google"]), \
                patch.object(seed_factory.SeedFactory, "harvest_google_taxonomy", add_seed), \
                patch.object(seed_factory.SeedFactory, "save") as save:
            result = seed_factory.main()

        self.assertEqual(result, 0)
        save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
