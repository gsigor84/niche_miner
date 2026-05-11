import argparse
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pipeline


def make_args(**overrides):
    values = {
        "keywords": None,
        "skip_seed": False,
        "skip_scout": False,
        "skip_gap": False,
        "niche_type": "saas",
        "subs": None,
        "max_posts": 10,
        "run_id": "test_run",
        "prefix": None,
        "only_pain_points": False,
        "max_seeds": 20,
        "input": None,
        "top_gaps": 20,
        "min_degree": 3,
        "viz": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class PipelineTests(unittest.TestCase):
    def test_fresh_full_run_plans_all_incomplete_phases(self):
        args = make_args()

        phases = [name for name, _ in pipeline.plan_pipeline_phases(args, {})]

        self.assertEqual(phases, ["seed", "scout", "fetch", "normalize", "gap"])

    def test_keyword_run_skips_seed_but_keeps_downstream_phases(self):
        args = make_args(keywords="crm tools")

        phases = [name for name, _ in pipeline.plan_pipeline_phases(args, {"seed": "done"})]

        self.assertEqual(phases, ["scout", "fetch", "normalize", "gap"])

    def test_normalize_phase_does_not_require_fetch_only_flags(self):
        args = SimpleNamespace(run_id="critical_regression")
        state = {}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "critical_regression_raw.jsonl").write_text("{}\n", encoding="utf-8")

            captured = {}

            def fake_run(cmd, label):
                captured["cmd"] = cmd
                captured["label"] = label

            with patch.object(pipeline, "DATA", tmp_path), \
                 patch.object(pipeline, "run", side_effect=fake_run), \
                 patch.object(pipeline, "save_run_state"):
                pipeline.run_phase_normalize(args, args.run_id, state)

        self.assertEqual(captured["label"], "PHASE 4: normalize")
        self.assertNotIn("--only_pain_points", captured["cmd"])
        self.assertEqual(state["normalize"], "done")

    def test_fetch_uses_argv_and_passes_prefix_and_pain_point_filter(self):
        args = make_args(
            run_id="fetch_run",
            subs="CRMSoftware,CRM",
            prefix="best crm",
            only_pain_points=True,
        )
        completed = SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

        with patch.object(pipeline.subprocess, "run", return_value=completed) as run_mock, \
             patch.object(pipeline, "save_run_state"):
            pipeline.run_phase_fetch(args, args.run_id, {})

        cmd = run_mock.call_args.args[0]
        kwargs = run_mock.call_args.kwargs
        self.assertIsInstance(cmd, list)
        self.assertNotIn("shell", kwargs)
        self.assertIn("--prefix", cmd)
        self.assertEqual(cmd[cmd.index("--prefix") + 1], "best crm")
        self.assertIn("--only_pain_points", cmd)

    def test_scout_uses_argv_for_keyword_phrases(self):
        args = make_args(keywords="crm tools,billing automation")
        completed = SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

        with patch.object(pipeline.subprocess, "run", return_value=completed) as run_mock, \
             patch.object(pipeline, "save_run_state"):
            pipeline.run_phase_scout(args, args.run_id, {})

        cmd = run_mock.call_args.args[0]
        kwargs = run_mock.call_args.kwargs
        self.assertEqual(cmd[:3], ["python3", "scout_subreddits.py", "crm tools,billing automation"])
        self.assertNotIn("shell", kwargs)

    def test_fetch_failure_does_not_mark_phase_done(self):
        args = make_args()
        state = {}
        completed = SimpleNamespace(returncode=2, stdout="", stderr="bad args\n")

        with patch.object(pipeline.subprocess, "run", return_value=completed), \
             patch.object(pipeline, "save_run_state") as save_mock:
            with self.assertRaises(SystemExit):
                pipeline.run_phase_fetch(args, args.run_id, state)

        self.assertNotEqual(state.get("fetch"), "done")
        save_mock.assert_not_called()

    def test_gap_failure_does_not_mark_phase_done(self):
        args = make_args(run_id="gap_failure")
        state = {}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "gap_failure_normalized.jsonl").write_text("{}\n", encoding="utf-8")

            with patch.object(pipeline, "DATA", tmp_path), \
                 patch.object(pipeline, "run", side_effect=SystemExit(1)), \
                 patch.object(pipeline, "save_run_state") as save_mock:
                with self.assertRaises(SystemExit):
                    pipeline.run_phase_gap(args, args.run_id, state)

        self.assertNotEqual(state.get("gap"), "done")
        save_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
