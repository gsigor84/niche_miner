import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pipeline
import seed_factory


class SeedFactorySafetyTests(unittest.TestCase):
    def test_failed_google_harvest_preserves_existing_seed_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            seed_path = Path(tmpdir) / "seed_topics.txt"
            original = "crm tools\nsales automation\n"
            seed_path.write_text(original, encoding="utf-8")

            with mock.patch.object(seed_factory, "OUTPUT_FILE", str(seed_path)), \
                 mock.patch.object(seed_factory.requests, "get", side_effect=RuntimeError("offline")), \
                 mock.patch.object(sys, "argv", ["seed_factory.py", "--source", "google"]):
                result = seed_factory.main()

            self.assertEqual(result, 1)
            self.assertEqual(seed_path.read_text(encoding="utf-8"), original)


class PipelineSafetyTests(unittest.TestCase):
    def test_full_pipeline_schedules_downstream_phases_after_state_updates(self):
        phases_run = []

        def fake_phase(name):
            def _run(args, run_id, state):
                phases_run.append(name)
                state[name] = "done"
            return _run

        with mock.patch.object(sys, "argv", [
            "pipeline.py",
            "--run_id", "unit_pipeline",
            "--topic", "crm tools",
            "--niche_type", "saas",
        ]), \
             mock.patch.object(pipeline, "run_phase_seed", fake_phase("seed")), \
             mock.patch.object(pipeline, "run_phase_scout", fake_phase("scout")), \
             mock.patch.object(pipeline, "run_phase_fetch", fake_phase("fetch")), \
             mock.patch.object(pipeline, "run_phase_normalize", fake_phase("normalize")), \
             mock.patch.object(pipeline, "run_phase_gap", fake_phase("gap")), \
             mock.patch.object(pipeline.time, "sleep"):
            pipeline.main()

        self.assertEqual(phases_run, ["seed", "scout", "fetch", "normalize", "gap"])

    def test_scout_phase_passes_keywords_without_shell(self):
        args = SimpleNamespace(
            keywords="crm; touch /tmp/should_not_run",
            max_seeds=5,
            subs=None,
        )
        state = {}
        completed = subprocess.CompletedProcess(
            args=["python3"],
            returncode=0,
            stdout="\n[SUCCESS] Top discovered subreddits: CRM\nTo use with rss_miner: --subs CRM\n",
            stderr="",
        )

        with mock.patch.object(pipeline.subprocess, "run", return_value=completed) as run_mock, \
             mock.patch.object(pipeline, "save_run_state"):
            pipeline.run_phase_scout(args, "unit", state)

        command = run_mock.call_args.args[0]
        kwargs = run_mock.call_args.kwargs
        self.assertIsInstance(command, list)
        self.assertIn("crm; touch /tmp/should_not_run", command)
        self.assertNotIn("shell", kwargs)
        self.assertEqual(state["subs"], "CRM")
        self.assertEqual(state["scout"], "done")


if __name__ == "__main__":
    unittest.main()
