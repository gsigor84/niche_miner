import argparse
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pipeline
import seed_factory


def pipeline_args(**overrides):
    values = {
        "run_id": "critical_run",
        "topic": "CRM tools",
        "keywords": None,
        "niche_type": "saas",
        "prefix": None,
        "subs": None,
        "resume": False,
        "phase": None,
        "seed_count": 3,
        "max_seeds": 5,
        "max_posts": 10,
        "only_pain_points": False,
        "top_gaps": 20,
        "min_degree": 3,
        "viz": False,
        "input": None,
        "skip_seed": False,
        "skip_gap": False,
        "skip_scout": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class PipelineCriticalFixTests(unittest.TestCase):
    def test_fresh_full_run_rechecks_state_and_runs_downstream_phases(self):
        phases = []

        def phase(name):
            def _run(args, run_id, state):
                phases.append(name)
                state[name] = "done"

            return _run

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(pipeline, "PROJECT", tmp_path), \
                 mock.patch.object(pipeline, "DATA", tmp_path / "data"), \
                 mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                 mock.patch.object(pipeline, "parse_args", return_value=pipeline_args()), \
                 mock.patch.object(pipeline, "run_phase_seed", phase("seed")), \
                 mock.patch.object(pipeline, "run_phase_scout", phase("scout")), \
                 mock.patch.object(pipeline, "run_phase_fetch", phase("fetch")), \
                 mock.patch.object(pipeline, "run_phase_normalize", phase("normalize")), \
                 mock.patch.object(pipeline, "run_phase_gap", phase("gap")), \
                 mock.patch.object(pipeline.time, "sleep"):
                pipeline.main()

        self.assertEqual(phases, ["seed", "scout", "fetch", "normalize", "gap"])

    def test_fetch_uses_cli_keywords_and_run_scoped_seen_file(self):
        captured = {}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_dir = tmp_path / "data"
            data_dir.mkdir()

            def fake_run(cmd, label, check=True, capture_output=False):
                captured["cmd"] = cmd
                (data_dir / "critical_run_raw.jsonl").write_text('{"post_id":"abc123"}\n')
                return argparse.Namespace(returncode=0, stdout="", stderr="")

            args = pipeline_args(
                keywords="crm tools,sales automation",
                prefix="best",
                only_pain_points=True,
            )
            state = {"scouted_subs": ["CRMSoftware", "CRM"]}

            with mock.patch.object(pipeline, "PROJECT", tmp_path), \
                 mock.patch.object(pipeline, "DATA", data_dir), \
                 mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                 mock.patch.object(pipeline, "run", side_effect=fake_run):
                pipeline.run_phase_fetch(args, args.run_id, state)

        cmd = captured["cmd"]
        self.assertIsInstance(cmd, list)
        self.assertIn("--keywords", cmd)
        self.assertEqual(cmd[cmd.index("--keywords") + 1], "crm tools,sales automation")
        self.assertIn("--seen", cmd)
        self.assertEqual(cmd[cmd.index("--seen") + 1], "data/critical_run_seen_post_ids.txt")
        self.assertIn("--prefix", cmd)
        self.assertIn("--only_pain_points", cmd)
        self.assertEqual(state["fetch"], "done")


class SeedFactoryCriticalFixTests(unittest.TestCase):
    def test_generation_failure_does_not_save_empty_seed_file(self):
        fake_factory = mock.Mock()
        fake_factory.seeds = set()
        fake_factory.harvest_google_taxonomy.return_value = None

        with mock.patch.object(seed_factory, "SeedFactory", return_value=fake_factory), \
             mock.patch("sys.argv", ["seed_factory.py", "--source", "google"]):
            with self.assertRaises(SystemExit) as cm:
                seed_factory.main()

        self.assertEqual(cm.exception.code, 1)
        fake_factory.save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
