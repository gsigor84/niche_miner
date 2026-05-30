import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pipeline


def make_args(**overrides):
    defaults = {
        "run_id": "test_run",
        "topic": None,
        "keywords": None,
        "niche_type": "saas",
        "prefix": None,
        "subs": None,
        "resume": False,
        "phase": None,
        "seed_count": 10,
        "max_seeds": 3,
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
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class PipelineCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.original_project = pipeline.PROJECT
        self.original_data = pipeline.DATA
        self.original_runs = pipeline.RUNS
        pipeline.PROJECT = self.tmp_path
        pipeline.DATA = self.tmp_path / "data"
        pipeline.RUNS = self.tmp_path / "runs"

    def tearDown(self):
        pipeline.PROJECT = self.original_project
        pipeline.DATA = self.original_data
        pipeline.RUNS = self.original_runs
        self.tmp.cleanup()

    def test_scout_phase_does_not_execute_keywords_through_shell(self):
        malicious_keywords = "crm; touch /tmp/pipeline-scout-pwned"
        args = make_args(keywords=malicious_keywords)
        state = {}

        completed = SimpleNamespace(returncode=0, stdout="ok")
        with patch("pipeline.subprocess.run", return_value=completed) as run_mock:
            pipeline.run_phase_scout(args, args.run_id, state)

        cmd = run_mock.call_args.args[0]
        kwargs = run_mock.call_args.kwargs
        self.assertEqual(
            cmd,
            ["python3", "scout_subreddits.py", malicious_keywords, "--limit", "3"],
        )
        self.assertNotEqual(kwargs.get("shell"), True)
        self.assertEqual(state["scout"], "done")

    def test_fetch_phase_does_not_execute_arguments_through_shell(self):
        malicious_subs = "python; touch /tmp/pipeline-fetch-pwned"
        args = make_args(
            run_id="run;touch /tmp/pipeline-runid-pwned",
            subs=malicious_subs,
            prefix="best; touch /tmp/pipeline-prefix-pwned",
            only_pain_points=True,
        )
        state = {}

        completed = SimpleNamespace(returncode=0, stdout="ok")
        with patch("pipeline.subprocess.run", return_value=completed) as run_mock:
            pipeline.run_phase_fetch(args, args.run_id, state)

        cmd = run_mock.call_args.args[0]
        kwargs = run_mock.call_args.kwargs
        self.assertIsInstance(cmd, list)
        self.assertNotEqual(kwargs.get("shell"), True)
        self.assertEqual(cmd[cmd.index("--subs") + 1], malicious_subs)
        self.assertEqual(cmd[cmd.index("--prefix") + 1], args.prefix)
        self.assertIn("--only_pain_points", cmd)
        self.assertEqual(state["fetch"], "done")

    def test_fresh_full_pipeline_runs_all_phases_once(self):
        args = make_args()
        calls = []

        def fake_phase(name):
            def phase_fn(parsed_args, run_id, state):
                calls.append(name)
                state[name] = "done"
                pipeline.save_run_state(run_id, state)

            return phase_fn

        with (
            patch("pipeline.parse_args", return_value=args),
            patch("pipeline.run_phase_seed", fake_phase("seed")),
            patch("pipeline.run_phase_scout", fake_phase("scout")),
            patch("pipeline.run_phase_fetch", fake_phase("fetch")),
            patch("pipeline.run_phase_normalize", fake_phase("normalize")),
            patch("pipeline.run_phase_gap", fake_phase("gap")),
            patch("pipeline.time.sleep", Mock()),
        ):
            pipeline.main()

        self.assertEqual(calls, ["seed", "scout", "fetch", "normalize", "gap"])


if __name__ == "__main__":
    unittest.main()
