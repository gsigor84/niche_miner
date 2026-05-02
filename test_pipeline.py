import argparse
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pipeline


def make_args(**overrides):
    defaults = {
        "keywords": None,
        "skip_seed": False,
        "skip_scout": False,
        "skip_gap": False,
        "max_seeds": 20,
        "niche_type": "saas",
        "subs": "CRMSoftware",
        "max_posts": 10,
        "run_id": "test_run",
        "prefix": None,
        "only_pain_points": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class PipelinePhasePlanningTests(unittest.TestCase):
    def test_fresh_run_plans_all_unskipped_phases(self):
        args = make_args()

        self.assertEqual(
            pipeline.plan_sequential_phases(args, {}),
            ["seed", "scout", "fetch", "normalize", "gap"],
        )

    def test_keywords_skip_seed_but_continue_full_pipeline(self):
        args = make_args(keywords="crm; touch /tmp/pwned")

        self.assertEqual(
            pipeline.plan_sequential_phases(args, {"seed": "done"}),
            ["scout", "fetch", "normalize", "gap"],
        )

    def test_resume_skips_completed_phases_only(self):
        args = make_args()

        self.assertEqual(
            pipeline.plan_sequential_phases(args, {"seed": "done", "scout": "done"}),
            ["fetch", "normalize", "gap"],
        )


class PipelineCommandTests(unittest.TestCase):
    def test_scout_uses_argv_not_shell_for_keywords(self):
        args = make_args(keywords="crm; touch /tmp/pwned")
        state = {}

        with patch.object(pipeline.subprocess, "run") as run_mock, \
                patch.object(pipeline, "save_run_state"):
            run_mock.return_value.returncode = 0
            run_mock.return_value.stdout = ""

            pipeline.run_phase_scout(args, args.run_id, state)

        cmd = run_mock.call_args.args[0]
        kwargs = run_mock.call_args.kwargs
        self.assertEqual(cmd, ["python3", "scout_subreddits.py", args.keywords, "--limit", "20"])
        self.assertNotIn("shell", kwargs)

    def test_fetch_passes_prefix_and_pain_filter_to_rss_miner(self):
        args = make_args(prefix="best", only_pain_points=True)
        state = {}

        with patch.object(pipeline.subprocess, "run") as run_mock, \
                patch.object(pipeline, "save_run_state"):
            run_mock.return_value.returncode = 0
            run_mock.return_value.stdout = ""

            pipeline.run_phase_fetch(args, args.run_id, state)

        cmd = run_mock.call_args.args[0]
        kwargs = run_mock.call_args.kwargs
        self.assertIn("--prefix", cmd)
        self.assertEqual(cmd[cmd.index("--prefix") + 1], "best")
        self.assertIn("--only_pain_points", cmd)
        self.assertIn("data/test_run_raw.jsonl", cmd)
        self.assertNotIn("shell", kwargs)

    def test_normalize_command_has_no_unknown_pain_point_option(self):
        args = make_args()
        state = {}

        with patch.object(Path, "exists", return_value=True), \
                patch.object(pipeline, "run") as run_mock, \
                patch.object(pipeline, "save_run_state"):
            pipeline.run_phase_normalize(args, args.run_id, state)

        cmd = run_mock.call_args.args[0]
        self.assertNotIn("--only_pain_points", cmd)
        self.assertTrue(any(arg.endswith("data/test_run_raw.jsonl") for arg in cmd))


if __name__ == "__main__":
    unittest.main()
