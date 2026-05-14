import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pipeline


class PipelineTests(unittest.TestCase):
    def make_args(self, **overrides):
        values = {
            "run_id": "test_run",
            "topic": "crm",
            "keywords": None,
            "niche_type": "saas",
            "prefix": None,
            "subs": None,
            "resume": False,
            "phase": None,
            "seed_count": 10,
            "max_seeds": 20,
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
        return SimpleNamespace(**values)

    def test_planned_phases_includes_downstream_phases_for_fresh_run(self):
        args = self.make_args()

        phase_names = [name for name, _ in pipeline.planned_phases(args, {})]

        self.assertEqual(phase_names, ["seed", "scout", "fetch", "normalize", "gap"])

    def test_fetch_command_preserves_prefix_and_uses_argv(self):
        args = self.make_args(prefix="best", subs=None, only_pain_points=True)
        state = {}

        with patch.object(pipeline, "save_run_state"), patch.object(pipeline, "run") as run_mock:
            pipeline.run_phase_fetch(args, "run42", state)

        cmd = run_mock.call_args.args[0]
        self.assertIsInstance(cmd, list)
        self.assertIn("--prefix", cmd)
        self.assertEqual(cmd[cmd.index("--prefix") + 1], "best")
        self.assertIn("--only_pain_points", cmd)
        self.assertNotIn("--subs", cmd)
        self.assertEqual(cmd[cmd.index("--out") + 1], "data/run42_raw.jsonl")
        self.assertEqual(state["fetch"], "done")

    def test_scout_command_keeps_keywords_as_single_argument(self):
        args = self.make_args(keywords="crm software,$(touch pwned)")
        state = {}

        with patch.object(pipeline, "save_run_state"), patch.object(pipeline, "run") as run_mock:
            pipeline.run_phase_scout(args, "run42", state)

        cmd = run_mock.call_args.args[0]
        self.assertEqual(cmd[0:2], ["python3", "scout_subreddits.py"])
        self.assertEqual(cmd[2], "crm software,$(touch pwned)")
        self.assertEqual(state["scout"], "done")

    def test_subprocess_failure_does_not_mark_fetch_done(self):
        args = self.make_args()
        state = {}

        with patch.object(pipeline, "run", side_effect=SystemExit(1)):
            with self.assertRaises(SystemExit):
                pipeline.run_phase_fetch(args, "run42", state)

        self.assertNotIn("fetch", state)

    def test_normalize_phase_does_not_require_only_pain_points_arg(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            runs_dir = Path(tmp) / "runs"
            data_dir.mkdir()
            (data_dir / "run42_raw.jsonl").write_text("{}", encoding="utf-8")
            args = SimpleNamespace(run_id="run42")
            state = {}

            with (
                patch.object(pipeline, "DATA", data_dir),
                patch.object(pipeline, "RUNS", runs_dir),
                patch.object(pipeline, "run") as run_mock,
            ):
                pipeline.run_phase_normalize(args, "run42", state)

        cmd = run_mock.call_args.args[0]
        self.assertNotIn("--only_pain_points", cmd)
        self.assertEqual(state["normalize"], "done")


if __name__ == "__main__":
    unittest.main()
