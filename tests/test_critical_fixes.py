import argparse
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pipeline


class PipelineCriticalFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        self.data = self.project / "data"
        self.runs = self.project / "runs"
        self.seed_file = self.project / "seed_topics.txt"

        self.original_project = pipeline.PROJECT
        self.original_data = pipeline.DATA
        self.original_runs = pipeline.RUNS
        self.original_seed_file = pipeline.SEED_FILE

        pipeline.PROJECT = self.project
        pipeline.DATA = self.data
        pipeline.RUNS = self.runs
        pipeline.SEED_FILE = self.seed_file

        self.data.mkdir()
        self.runs.mkdir()

    def tearDown(self):
        pipeline.PROJECT = self.original_project
        pipeline.DATA = self.original_data
        pipeline.RUNS = self.original_runs
        pipeline.SEED_FILE = self.original_seed_file
        self.tmp.cleanup()

    def test_fresh_full_run_executes_downstream_phases_after_state_changes(self):
        executed = []

        def phase(name):
            def _run(args, run_id, state):
                executed.append(name)
                state[name] = "done"
                pipeline.save_run_state(run_id, state)
            return _run

        patches = [
            patch.object(pipeline, "run_phase_seed", phase("seed")),
            patch.object(pipeline, "run_phase_scout", phase("scout")),
            patch.object(pipeline, "run_phase_fetch", phase("fetch")),
            patch.object(pipeline, "run_phase_normalize", phase("normalize")),
            patch.object(pipeline, "run_phase_gap", phase("gap")),
            patch.object(pipeline.time, "sleep", lambda _: None),
            patch.object(sys, "argv", ["pipeline.py", "--run_id", "fresh", "--topic", "crm"]),
        ]
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            pipeline.main()

        self.assertEqual(["seed", "scout", "fetch", "normalize", "gap"], executed)
        state = json.loads((self.runs / "fresh" / "state.json").read_text())
        self.assertEqual({phase: "done" for phase in executed}, state)

    def test_fetch_failure_exits_without_marking_phase_done(self):
        args = argparse.Namespace(
            run_id="broken",
            subs="CRMSoftware",
            niche_type="saas",
            max_posts=10,
            max_seeds=2,
            keywords="crm tools",
            prefix=None,
            only_pain_points=False,
        )
        state = {}

        with patch.object(
            pipeline.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(["rss"], 1),
        ):
            with self.assertRaises(SystemExit) as cm:
                pipeline.run_phase_fetch(args, "broken", state)

        self.assertEqual(1, cm.exception.code)
        self.assertNotIn("fetch", state)
        self.assertFalse((self.runs / "broken" / "state.json").exists())

    def test_fetch_uses_run_inputs_and_run_scoped_seen_file(self):
        args = argparse.Namespace(
            run_id="targeted",
            subs=None,
            niche_type="saas",
            max_posts=10,
            max_seeds=1,
            keywords="crm tools,sales automation",
            prefix="best",
            only_pain_points=True,
        )
        state = {}
        (self.runs / "targeted").mkdir()
        (self.runs / "targeted" / "subreddits.txt").write_text("CRMSoftware,CRM")
        captured = []

        def fake_run(cmd, cwd, capture_output, text):
            captured.append(cmd)
            (self.data / "targeted_raw.jsonl").write_text('{"post_id":"abc123"}\n')
            return subprocess.CompletedProcess(cmd, 0)

        with patch.object(pipeline.subprocess, "run", side_effect=fake_run):
            pipeline.run_phase_fetch(args, "targeted", state)

        cmd = captured[0]
        self.assertIsInstance(cmd, list)
        self.assertIn("--keywords", cmd)
        self.assertEqual("crm tools,sales automation", cmd[cmd.index("--keywords") + 1])
        self.assertIn("--prefix", cmd)
        self.assertEqual("best", cmd[cmd.index("--prefix") + 1])
        self.assertIn("--only_pain_points", cmd)
        self.assertIn("--seen", cmd)
        self.assertEqual(str(self.data / "targeted_seen_post_ids.txt"), cmd[cmd.index("--seen") + 1])
        self.assertEqual("CRMSoftware,CRM", cmd[cmd.index("--subs") + 1])
        self.assertEqual("done", state["fetch"])

    def test_single_phase_preserves_existing_run_state(self):
        run_dir = self.runs / "resume"
        run_dir.mkdir()
        (run_dir / "state.json").write_text(json.dumps({"seed": "done", "scout": "done"}))

        def fake_fetch(args, run_id, state):
            state["fetch"] = "done"
            pipeline.save_run_state(run_id, state)

        with patch.object(pipeline, "run_phase_fetch", fake_fetch), patch.object(
            sys, "argv", ["pipeline.py", "--phase", "fetch", "--run_id", "resume"]
        ):
            with self.assertRaises(SystemExit) as cm:
                pipeline.main()

        self.assertEqual(0, cm.exception.code)
        state = json.loads((run_dir / "state.json").read_text())
        self.assertEqual({"seed": "done", "scout": "done", "fetch": "done"}, state)


if __name__ == "__main__":
    unittest.main()
