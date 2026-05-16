import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pipeline


class PipelineTests(unittest.TestCase):
    def test_keyword_run_executes_downstream_phases_in_same_invocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            calls = []

            def phase(name):
                def _run(args, run_id, state):
                    calls.append(name)
                    state[name] = "done"
                    pipeline.save_run_state(run_id, state)
                return _run

            argv = [
                "pipeline.py",
                "--run_id", "unit_run",
                "--keywords", "crm tools",
                "--skip_gap",
            ]
            with mock.patch.object(pipeline, "DATA", tmp_path / "data"), \
                    mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                    mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(pipeline, "run_phase_seed", phase("seed")), \
                    mock.patch.object(pipeline, "run_phase_scout", phase("scout")), \
                    mock.patch.object(pipeline, "run_phase_fetch", phase("fetch")), \
                    mock.patch.object(pipeline, "run_phase_normalize", phase("normalize")):
                pipeline.main()

            self.assertEqual(calls, ["scout", "fetch", "normalize"])

    def test_fetch_uses_argv_and_preserves_multi_word_options(self):
        captured = {}

        def fake_run(cmd, label, check=True):
            captured["cmd"] = cmd
            captured["label"] = label
            return SimpleNamespace(returncode=0)

        args = SimpleNamespace(
            niche_type="saas",
            subs="CRMSoftware",
            max_posts=5,
            run_id="unit_run",
            prefix="best value",
            only_pain_points=True,
        )
        state = {}

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(pipeline, "RUNS", Path(tmp) / "runs"), \
                mock.patch.object(pipeline, "run", fake_run):
            pipeline.run_phase_fetch(args, "unit_run", state)

        self.assertEqual(captured["label"], "PHASE 3: rss_miner")
        self.assertEqual(captured["cmd"][0:2], ["python3", "rss_miner.py"])
        self.assertIn("--prefix", captured["cmd"])
        self.assertEqual(captured["cmd"][captured["cmd"].index("--prefix") + 1], "best value")
        self.assertIn("--only_pain_points", captured["cmd"])
        self.assertEqual(state["fetch"], "done")

    def test_fetch_failure_does_not_mark_phase_done(self):
        def failing_run(cmd, label, check=True):
            raise SystemExit(1)

        args = SimpleNamespace(
            niche_type="saas",
            subs="CRMSoftware",
            max_posts=5,
            run_id="unit_run",
            prefix=None,
            only_pain_points=False,
        )
        state = {}

        with mock.patch.object(pipeline, "run", failing_run), self.assertRaises(SystemExit):
            pipeline.run_phase_fetch(args, "unit_run", state)

        self.assertNotIn("fetch", state)

    def test_normalize_does_not_pass_fetch_only_pain_filter(self):
        captured = {}

        def fake_run(cmd, label, check=True):
            captured["cmd"] = cmd
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_path = tmp_path / "data"
            data_path.mkdir()
            (data_path / "unit_run_raw.jsonl").write_text("{}\n", encoding="utf-8")

            args = SimpleNamespace(run_id="unit_run", only_pain_points=True)
            state = {}

            with mock.patch.object(pipeline, "DATA", data_path), \
                    mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                    mock.patch.object(pipeline, "run", fake_run):
                pipeline.run_phase_normalize(args, "unit_run", state)

        self.assertNotIn("--only_pain_points", captured["cmd"])
        self.assertEqual(state["normalize"], "done")


if __name__ == "__main__":
    unittest.main()
