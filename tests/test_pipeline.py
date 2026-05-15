import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pipeline


class PipelineTest(unittest.TestCase):
    def run_main_with_stubs(self, argv, initial_state=None):
        calls = []
        original_paths = (pipeline.DATA, pipeline.RUNS, pipeline.SEED_FILE)
        original_phases = (
            pipeline.run_phase_seed,
            pipeline.run_phase_scout,
            pipeline.run_phase_fetch,
            pipeline.run_phase_normalize,
            pipeline.run_phase_gap,
        )

        def phase(name):
            def _stub(args, run_id, state):
                calls.append(name)
                state[name] = "done"
                pipeline.save_run_state(run_id, state)
            return _stub

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pipeline.DATA = root / "data"
            pipeline.RUNS = root / "runs"
            pipeline.SEED_FILE = root / "seed_topics.txt"
            pipeline.run_phase_seed = phase("seed")
            pipeline.run_phase_scout = phase("scout")
            pipeline.run_phase_fetch = phase("fetch")
            pipeline.run_phase_normalize = phase("normalize")
            pipeline.run_phase_gap = phase("gap")
            pipeline.ensure_dir(pipeline.RUNS / "run1")
            if initial_state is not None:
                (pipeline.RUNS / "run1" / "state.json").write_text(
                    json.dumps(initial_state),
                    encoding="utf-8",
                )

            try:
                with mock.patch.object(sys, "argv", argv), mock.patch.object(pipeline.time, "sleep"):
                    pipeline.main()
            finally:
                (
                    pipeline.DATA,
                    pipeline.RUNS,
                    pipeline.SEED_FILE,
                ) = original_paths
                (
                    pipeline.run_phase_seed,
                    pipeline.run_phase_scout,
                    pipeline.run_phase_fetch,
                    pipeline.run_phase_normalize,
                    pipeline.run_phase_gap,
                ) = original_phases

        return calls

    def test_fresh_run_executes_all_downstream_phases(self):
        calls = self.run_main_with_stubs([
            "pipeline.py",
            "--run_id",
            "run1",
            "--topic",
            "party tickets",
            "--niche_type",
            "events",
        ])

        self.assertEqual(calls, ["seed", "scout", "fetch", "normalize", "gap"])

    def test_resume_continues_after_completed_upstream_phases(self):
        calls = self.run_main_with_stubs(
            ["pipeline.py", "--resume", "--run_id", "run1"],
            initial_state={"seed": "done", "scout": "done"},
        )

        self.assertEqual(calls, ["fetch", "normalize", "gap"])

    def test_scout_uses_argv_and_preserves_keyword_phrases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_runs = pipeline.RUNS
            pipeline.RUNS = Path(tmpdir) / "runs"
            args = SimpleNamespace(keywords="party tickets,small business", max_seeds=5)
            completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok")
            try:
                with mock.patch.object(pipeline.subprocess, "run", return_value=completed) as run_mock:
                    state = {}
                    pipeline.run_phase_scout(args, "run1", state)
            finally:
                pipeline.RUNS = original_runs

        cmd = run_mock.call_args.args[0]
        kwargs = run_mock.call_args.kwargs
        self.assertEqual(cmd, ["python3", "scout_subreddits.py", args.keywords, "--limit", "5"])
        self.assertNotIn("shell", kwargs)
        self.assertEqual(state, {"scout": "done"})

    def test_fetch_passes_prefix_and_pain_filter_without_shell(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_paths = (pipeline.DATA, pipeline.RUNS)
            pipeline.DATA = Path(tmpdir) / "data"
            pipeline.RUNS = Path(tmpdir) / "runs"
            args = SimpleNamespace(
                niche_type="events",
                subs="eventplanning,startups",
                max_posts=3,
                run_id="run1",
                prefix="local",
                only_pain_points=True,
            )
            completed = subprocess.CompletedProcess(args=[], returncode=0)
            try:
                with mock.patch.object(pipeline.subprocess, "run", return_value=completed) as run_mock:
                    state = {}
                    pipeline.run_phase_fetch(args, "run1", state)
            finally:
                pipeline.DATA, pipeline.RUNS = original_paths

        cmd = run_mock.call_args.args[0]
        kwargs = run_mock.call_args.kwargs
        self.assertNotIn("shell", kwargs)
        self.assertIn("--prefix", cmd)
        self.assertIn("local", cmd)
        self.assertIn("--only_pain_points", cmd)
        self.assertEqual(state, {"fetch": "done"})

    def test_gap_failure_does_not_mark_state_done(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_paths = (pipeline.DATA, pipeline.RUNS)
            pipeline.DATA = Path(tmpdir) / "data"
            pipeline.RUNS = Path(tmpdir) / "runs"
            pipeline.DATA.mkdir()
            (pipeline.DATA / "run1_normalized.jsonl").write_text("{}", encoding="utf-8")
            args = SimpleNamespace(
                input=None,
                run_id="run1",
                top_gaps=20,
                min_degree=3,
                viz=False,
            )
            completed = subprocess.CompletedProcess(args=[], returncode=1)
            try:
                with mock.patch.object(pipeline.subprocess, "run", return_value=completed):
                    state = {}
                    with self.assertRaises(SystemExit):
                        pipeline.run_phase_gap(args, "run1", state)
            finally:
                pipeline.DATA, pipeline.RUNS = original_paths

        self.assertEqual(state, {})


if __name__ == "__main__":
    unittest.main()
