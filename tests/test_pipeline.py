import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pipeline


class PipelineTests(unittest.TestCase):
    def test_full_pipeline_runs_all_phases_in_one_invocation(self):
        calls = []

        def fake_phase(name):
            def _run(args, run_id, state):
                calls.append(name)
                state[name] = "done"
                pipeline.save_run_state(run_id, state)

            return _run

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(pipeline, "DATA", Path(tmpdir) / "data"), patch.object(
            pipeline, "RUNS", Path(tmpdir) / "runs"
        ), patch.object(pipeline, "run_phase_seed", fake_phase("seed")), patch.object(
            pipeline, "run_phase_scout", fake_phase("scout")
        ), patch.object(
            pipeline, "run_phase_fetch", fake_phase("fetch")
        ), patch.object(
            pipeline, "run_phase_normalize", fake_phase("normalize")
        ), patch.object(
            pipeline, "run_phase_gap", fake_phase("gap")
        ), patch.object(
            pipeline.time, "sleep", Mock()
        ), patch.object(
            sys,
            "argv",
            [
                "pipeline.py",
                "--run_id",
                "test_run",
                "--topic",
                "AI agents",
                "--subs",
                "SaaS",
            ],
        ), contextlib.redirect_stdout(io.StringIO()):
            pipeline.main()

        self.assertEqual(calls, ["seed", "scout", "fetch", "normalize", "gap"])

    def test_scout_phase_does_not_shell_interpolate_keywords(self):
        args = SimpleNamespace(
            keywords="crm tools; touch /tmp/pipeline_injected",
            max_seeds=5,
        )
        completed = SimpleNamespace(returncode=0, stdout="ok")

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(pipeline, "RUNS", Path(tmpdir) / "runs"), patch.object(
            pipeline.subprocess, "run", return_value=completed
        ) as run_mock, contextlib.redirect_stdout(io.StringIO()):
            pipeline.run_phase_scout(args, "test_run", {})

        cmd = run_mock.call_args.args[0]
        kwargs = run_mock.call_args.kwargs
        self.assertIsInstance(cmd, list)
        self.assertEqual(cmd[2], args.keywords)
        self.assertFalse(kwargs.get("shell", False))

    def test_fetch_phase_does_not_shell_interpolate_arguments(self):
        args = SimpleNamespace(
            niche_type="saas",
            subs="SaaS; touch /tmp/pipeline_injected",
            max_posts=10,
            run_id="test_run",
            prefix="best; touch /tmp/pipeline_injected",
        )
        completed = SimpleNamespace(returncode=0, stdout="ok")

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(pipeline, "DATA", Path(tmpdir) / "data"), patch.object(
            pipeline, "RUNS", Path(tmpdir) / "runs"
        ), patch.object(
            pipeline.subprocess, "run", return_value=completed
        ) as run_mock, contextlib.redirect_stdout(io.StringIO()):
            pipeline.run_phase_fetch(args, "test_run", {})

        cmd = run_mock.call_args.args[0]
        kwargs = run_mock.call_args.kwargs
        self.assertIsInstance(cmd, list)
        self.assertEqual(cmd[cmd.index("--subs") + 1], args.subs)
        self.assertEqual(cmd[cmd.index("--prefix") + 1], args.prefix)
        self.assertFalse(kwargs.get("shell", False))


if __name__ == "__main__":
    unittest.main()
