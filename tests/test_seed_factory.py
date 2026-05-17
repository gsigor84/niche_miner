import sys
import unittest
from unittest import mock

import seed_factory


class SeedFactoryTests(unittest.TestCase):
    def test_generation_failure_refuses_to_save_empty_seed_file(self):
        argv = ["seed_factory.py", "--source", "google"]

        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(seed_factory.SeedFactory, "harvest_google_taxonomy", return_value=None), \
                mock.patch.object(seed_factory.SeedFactory, "save") as save_mock:
            with self.assertRaises(SystemExit) as ctx:
                seed_factory.main()

        self.assertEqual(ctx.exception.code, 1)
        save_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
