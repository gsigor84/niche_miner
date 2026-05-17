import argparse
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pipeline


class PipelineTests(unittest.TestCase):
    def test_full_run_executes_downstream_phases_after_state_updates(self):
        calls = []

        def phase(name):
            def _run(args, run_id, state):
                calls.append(name)
                state[name] = "done"
                pipeline.save_run_state(run_id, state)
            return _run

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                    mock.patch.object(pipeline, "DATA", tmp_path / "data"), \
                    mock.patch.object(pipeline, "run_phase_seed", phase("seed")), \
                    mock.patch.object(pipeline, "run_phase_scout", phase("scout")), \
                    mock.patch.object(pipeline, "run_phase_fetch", phase("fetch")), \
                    mock.patch.object(pipeline, "run_phase_normalize", phase("normalize")), \
                    mock.patch.object(pipeline.time, "sleep", return_value=None), \
                    mock.patch.object(sys, "argv", ["pipeline.py", "--run_id", "unit", "--skip_gap"]):
                pipeline.main()

        self.assertEqual(calls, ["seed", "scout", "fetch", "normalize"])

    def test_normalize_phase_does_not_require_fetch_only_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_dir = tmp_path / "data"
            data_dir.mkdir()
            (data_dir / "unit_raw.jsonl").write_text(
                '{"title":"Help","url":"https://example.com","post_id":"abcde","comments":[]}\n',
                encoding="utf-8",
            )
            state = {}
            args = argparse.Namespace(run_id="unit")

            with mock.patch.object(pipeline, "DATA", data_dir), \
                    mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                    mock.patch.object(pipeline, "run") as run_mock:
                pipeline.run_phase_normalize(args, "unit", state)

        self.assertEqual(state["normalize"], "done")
        cmd = run_mock.call_args.args[0]
        self.assertNotIn("--only_pain_points", cmd)

    def test_fetch_phase_uses_argv_and_forwards_keywords(self):
        args = argparse.Namespace(
            niche_type="saas",
            subs="CRMSoftware",
            max_posts=5,
            run_id="unit",
            prefix="best",
            keywords="crm tools, sales automation",
            only_pain_points=True,
        )
        state = {}

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(pipeline, "RUNS", Path(tmp) / "runs"), \
                    mock.patch.object(pipeline, "run") as run_mock:
                pipeline.run_phase_fetch(args, "unit", state)

        cmd = run_mock.call_args.args[0]
        self.assertIsInstance(cmd, list)
        self.assertIn("--keywords", cmd)
        self.assertEqual(cmd[cmd.index("--keywords") + 1], "crm tools, sales automation")
        self.assertIn("--prefix", cmd)
        self.assertEqual(cmd[cmd.index("--prefix") + 1], "best")
        self.assertIn("--only_pain_points", cmd)
        self.assertEqual(state["fetch"], "done")


if __name__ == "__main__":
    unittest.main()
