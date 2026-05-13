import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pipeline


class PipelinePhaseTests(unittest.TestCase):
    def test_fresh_run_executes_all_phases_in_order(self):
        calls = []

        def make_phase(name):
            def phase(args, run_id, state):
                calls.append(name)
                state[name] = "done"
                pipeline.save_run_state(run_id, state)

            return phase

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            argv = [
                "pipeline.py",
                "--run_id",
                "unit_run",
                "--topic",
                "crm tools",
            ]
            patches = [
                patch.object(pipeline, "DATA", tmp_path / "data"),
                patch.object(pipeline, "RUNS", tmp_path / "runs"),
                patch.object(pipeline, "run_phase_seed", make_phase("seed")),
                patch.object(pipeline, "run_phase_scout", make_phase("scout")),
                patch.object(pipeline, "run_phase_fetch", make_phase("fetch")),
                patch.object(pipeline, "run_phase_normalize", make_phase("normalize")),
                patch.object(pipeline, "run_phase_gap", make_phase("gap")),
                patch("sys.argv", argv),
                patch.object(pipeline.time, "sleep", lambda _seconds: None),
            ]
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8]:
                pipeline.main()

        self.assertEqual(calls, ["seed", "scout", "fetch", "normalize", "gap"])

    def test_scout_preserves_keyword_phrases_and_saves_discovered_subs(self):
        args = Namespace(keywords="crm software,sales automation", max_seeds=5, subs=None)
        state = {}

        def fake_run(cmd, **kwargs):
            self.assertEqual(
                cmd,
                [
                    "python3",
                    "scout_subreddits.py",
                    "crm software,sales automation",
                    "--limit",
                    "5",
                ],
            )
            self.assertFalse(kwargs.get("shell", False))
            return SimpleNamespace(
                returncode=0,
                stdout="To use with rss_miner: --subs CRMSoftware,Sales\n",
                stderr="",
            )

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(pipeline, "RUNS", Path(tmp) / "runs"), patch.object(
                pipeline.subprocess, "run", fake_run
            ):
                pipeline.run_phase_scout(args, "unit_run", state)

        self.assertEqual(args.subs, "CRMSoftware,Sales")
        self.assertEqual(state["subs"], "CRMSoftware,Sales")
        self.assertEqual(state["scout"], "done")

    def test_fetch_uses_argv_prefix_and_does_not_mark_failed_runs_done(self):
        args = Namespace(
            niche_type="saas",
            max_posts=10,
            run_id="unit_run",
            subs=None,
            prefix="best crm",
            only_pain_points=True,
        )
        state = {"subs": "CRMSoftware"}

        def fake_run(cmd, **kwargs):
            self.assertIn("--subs", cmd)
            self.assertEqual(cmd[cmd.index("--subs") + 1], "CRMSoftware")
            self.assertIn("--prefix", cmd)
            self.assertEqual(cmd[cmd.index("--prefix") + 1], "best crm")
            self.assertIn("--only_pain_points", cmd)
            self.assertFalse(kwargs.get("shell", False))
            return SimpleNamespace(returncode=7, stdout="", stderr="boom")

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(pipeline, "RUNS", Path(tmp) / "runs"), patch.object(
                pipeline.subprocess, "run", fake_run
            ):
                with self.assertRaises(SystemExit):
                    pipeline.run_phase_fetch(args, "unit_run", state)

        self.assertNotEqual(state.get("fetch"), "done")


if __name__ == "__main__":
    unittest.main()
