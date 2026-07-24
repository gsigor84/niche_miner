import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pipeline
import gap_analysis


class PipelineCriticalFixTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.tmp_path = Path(self.tmpdir.name)
        self.data = self.tmp_path / "data"
        self.runs = self.tmp_path / "runs"
        self.seed_file = self.tmp_path / "seed_topics.txt"

        patchers = [
            mock.patch.object(pipeline, "DATA", self.data),
            mock.patch.object(pipeline, "RUNS", self.runs),
            mock.patch.object(pipeline, "SEED_FILE", self.seed_file),
            mock.patch.object(pipeline.time, "sleep", lambda _seconds: None),
        ]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_fresh_full_run_executes_all_phases_against_live_state(self):
        executed = []

        def fake_phase(name):
            def _phase(args, run_id, state):
                executed.append(name)
                state[name] = "done"
                pipeline.save_run_state(run_id, state)
            return _phase

        with mock.patch.object(sys, "argv", ["pipeline.py", "--run_id", "critical_run"]), \
             mock.patch.object(pipeline, "run_phase_seed", fake_phase("seed")), \
             mock.patch.object(pipeline, "run_phase_scout", fake_phase("scout")), \
             mock.patch.object(pipeline, "run_phase_fetch", fake_phase("fetch")), \
             mock.patch.object(pipeline, "run_phase_normalize", fake_phase("normalize")), \
             mock.patch.object(pipeline, "run_phase_gap", fake_phase("gap")):
            pipeline.main()

        self.assertEqual(executed, ["seed", "scout", "fetch", "normalize", "gap"])
        state = json.loads((self.runs / "critical_run" / "state.json").read_text())
        self.assertEqual(
            {phase: state.get(phase) for phase in ["seed", "scout", "fetch", "normalize", "gap"]},
            {"seed": "done", "scout": "done", "fetch": "done", "normalize": "done", "gap": "done"},
        )

    def test_single_phase_preserves_existing_run_state(self):
        run_dir = self.runs / "critical_run"
        run_dir.mkdir(parents=True)
        (run_dir / "state.json").write_text(json.dumps({"seed": "done", "scout": "done"}))

        def fake_fetch(args, run_id, state):
            state["fetch"] = "done"
            pipeline.save_run_state(run_id, state)

        with mock.patch.object(sys, "argv", ["pipeline.py", "--phase", "fetch", "--run_id", "critical_run"]), \
             mock.patch.object(pipeline, "run_phase_fetch", fake_fetch):
            with self.assertRaises(SystemExit) as raised:
                pipeline.main()

        self.assertEqual(raised.exception.code, 0)
        state = json.loads((run_dir / "state.json").read_text())
        self.assertEqual(state, {"seed": "done", "scout": "done", "fetch": "done"})

    def test_fetch_forwards_keywords_prefix_pain_filter_and_scouted_subs(self):
        captured = {}

        def fake_run(cmd, label, check=True):
            captured["cmd"] = cmd
            captured["label"] = label
            out = self.data / "critical_run_raw.jsonl"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("{}\n")

        args = SimpleNamespace(
            niche_type="saas",
            max_posts=7,
            max_seeds=3,
            run_id="critical_run",
            keywords="crm tools,sales automation",
            prefix="best",
            only_pain_points=True,
            subs=None,
        )

        with mock.patch.object(pipeline, "run", fake_run):
            pipeline.run_phase_fetch(args, "critical_run", {"scout_subs": ["CRM", "sales"]})

        cmd = captured["cmd"]
        self.assertIsInstance(cmd, list)
        self.assertIn("--keywords", cmd)
        self.assertEqual(cmd[cmd.index("--keywords") + 1], "crm tools,sales automation")
        self.assertIn("--prefix", cmd)
        self.assertEqual(cmd[cmd.index("--prefix") + 1], "best")
        self.assertIn("--only_pain_points", cmd)
        self.assertIn("--subs", cmd)
        self.assertEqual(cmd[cmd.index("--subs") + 1], "CRM,sales")
        self.assertIn("--max_keywords", cmd)
        self.assertEqual(cmd[cmd.index("--max_keywords") + 1], "3")
        self.assertEqual(cmd[cmd.index("--seen") + 1], str(self.runs / "critical_run" / "seen_post_ids.txt"))

    def test_normalize_does_not_forward_unsupported_pain_filter_flag(self):
        captured = {}
        raw = self.data / "critical_run_raw.jsonl"
        raw.parent.mkdir(parents=True)
        raw.write_text("{}\n")

        def fake_run(cmd, label, check=True):
            captured["cmd"] = cmd

        args = SimpleNamespace(run_id="critical_run", only_pain_points=True)

        with mock.patch.object(pipeline, "run", fake_run):
            pipeline.run_phase_normalize(args, "critical_run", {})

        self.assertNotIn("--only_pain_points", captured["cmd"])
        self.assertEqual(
            captured["cmd"],
            [
                "python3",
                "normalize_reddit_jsonl.py",
                "--input",
                str(raw),
                "--output",
                str(self.data / "critical_run_normalized.jsonl"),
            ],
        )

    def test_scout_uses_single_argv_keyword_argument_and_persists_handoff(self):
        captured = {}

        def fake_subprocess_run(cmd, **kwargs):
            captured["cmd"] = cmd
            return SimpleNamespace(
                returncode=0,
                stdout="[SUCCESS] Top discovered subreddits: CRM, sales\nTo use with rss_miner: --subs CRM,sales\n",
                stderr="",
            )

        args = SimpleNamespace(
            keywords="crm tools,sales automation",
            max_seeds=5,
            subs=None,
        )
        state = {}

        with mock.patch.object(pipeline.subprocess, "run", fake_subprocess_run):
            pipeline.run_phase_scout(args, "critical_run", state)

        self.assertEqual(captured["cmd"][:3], ["python3", "scout_subreddits.py", "crm tools,sales automation"])
        self.assertEqual(state["scout_subs"], ["CRM", "sales"])
        self.assertEqual(state["scout"], "done")

    def test_gap_viz_png_output_uses_separate_json_path(self):
        json_path, viz_path = gap_analysis.resolve_output_paths("/tmp/critical_gaps.png", True)

        self.assertEqual(json_path, Path("/tmp/critical_gaps.json"))
        self.assertEqual(viz_path, Path("/tmp/critical_gaps.png"))


if __name__ == "__main__":
    unittest.main()
