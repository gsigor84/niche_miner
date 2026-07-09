import io
import json
import os
import sys
import tempfile
import types
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

import pipeline
import seed_factory


class PipelineCriticalFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.runs = self.root / "runs"
        self.data.mkdir()
        self.runs.mkdir()
        self.seed_file = self.root / "seed_topics.txt"

        patches = [
            mock.patch.object(pipeline, "PROJECT", self.root),
            mock.patch.object(pipeline, "DATA", self.data),
            mock.patch.object(pipeline, "RUNS", self.runs),
            mock.patch.object(pipeline, "SEED_FILE", self.seed_file),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def args(self, **overrides):
        base = {
            "run_id": "critical_run",
            "topic": "party tickets",
            "keywords": None,
            "niche_type": "events",
            "prefix": None,
            "subs": None,
            "resume": False,
            "phase": None,
            "seed_count": 3,
            "max_seeds": 2,
            "max_posts": 1,
            "only_pain_points": False,
            "top_gaps": 5,
            "min_degree": 1,
            "viz": False,
            "input": None,
            "skip_seed": False,
            "skip_gap": False,
            "skip_scout": False,
        }
        base.update(overrides)
        return Namespace(**base)

    def test_normalize_phase_does_not_reference_fetch_only_flag(self):
        raw = self.data / "critical_run_raw.jsonl"
        raw.write_text('{"post_id":"abc123"}\n', encoding="utf-8")
        captured = {}

        def fake_run(cmd, label, check=True):
            captured["cmd"] = cmd
            return types.SimpleNamespace(returncode=0)

        with mock.patch.object(pipeline, "run", side_effect=fake_run):
            pipeline.run_phase_normalize(self.args(), "critical_run", {})

        self.assertNotIn("--only_pain_points", captured["cmd"])

    def test_scout_uses_argv_and_persists_discovered_subreddits(self):
        self.seed_file.write_text("# Generated\nparty tickets\nconcert tickets\n", encoding="utf-8")
        calls = {}

        def fake_subprocess_run(cmd, **kwargs):
            calls["cmd"] = cmd
            calls["kwargs"] = kwargs
            out_path = Path(cmd[cmd.index("--out") + 1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text("events,Ticketmaster", encoding="utf-8")
            return types.SimpleNamespace(returncode=0, stdout="To use with rss_miner: --subs events,Ticketmaster\n", stderr="")

        with mock.patch.object(pipeline.subprocess, "run", side_effect=fake_subprocess_run):
            state = {}
            pipeline.run_phase_scout(self.args(), "critical_run", state)

        self.assertIsInstance(calls["cmd"], list)
        self.assertNotIn("shell", calls["kwargs"])
        self.assertEqual(pipeline.load_scouted_subs("critical_run"), ["events", "Ticketmaster"])
        self.assertEqual(state["scout"], "done")

    def test_fetch_uses_scouted_subs_keywords_prefix_and_run_scoped_seen_file(self):
        pipeline.scouted_subs_file("critical_run").parent.mkdir(parents=True, exist_ok=True)
        pipeline.scouted_subs_file("critical_run").write_text("events,Ticketmaster", encoding="utf-8")
        calls = {}

        def fake_subprocess_run(cmd, **kwargs):
            calls["cmd"] = cmd
            calls["kwargs"] = kwargs
            raw_path = Path(cmd[cmd.index("--out") + 1])
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text('{"post_id":"abc123"}\n', encoding="utf-8")
            return types.SimpleNamespace(returncode=0, stdout="saved: abc123\n", stderr="")

        args = self.args(keywords="party tickets,ticket resale", prefix="best", only_pain_points=True)
        with mock.patch.object(pipeline.subprocess, "run", side_effect=fake_subprocess_run):
            state = {}
            pipeline.run_phase_fetch(args, "critical_run", state)

        cmd = calls["cmd"]
        self.assertIsInstance(cmd, list)
        self.assertNotIn("shell", calls["kwargs"])
        self.assertEqual(cmd[cmd.index("--subs") + 1], "events,Ticketmaster")
        self.assertEqual(cmd[cmd.index("--keywords") + 1], "party tickets,ticket resale")
        self.assertEqual(cmd[cmd.index("--prefix") + 1], "best")
        self.assertIn("--only_pain_points", cmd)
        self.assertEqual(Path(cmd[cmd.index("--seen") + 1]).name, "critical_run_seen_post_ids.txt")
        self.assertEqual(state["fetch"], "done")

    def test_full_pipeline_runs_downstream_phases_after_state_updates(self):
        order = []

        def make_phase(name):
            def phase(_args, _run_id, state):
                order.append(name)
                state[name] = "done"
                pipeline.save_run_state(_run_id, state)
            return phase

        test_args = self.args(run_id=None, topic="party tickets")
        test_args.skip_seed = False
        with mock.patch.object(pipeline, "parse_args", return_value=test_args), \
             mock.patch.object(pipeline, "run_phase_seed", side_effect=make_phase("seed")), \
             mock.patch.object(pipeline, "run_phase_scout", side_effect=make_phase("scout")), \
             mock.patch.object(pipeline, "run_phase_fetch", side_effect=make_phase("fetch")), \
             mock.patch.object(pipeline, "run_phase_normalize", side_effect=make_phase("normalize")), \
             mock.patch.object(pipeline, "run_phase_gap", side_effect=make_phase("gap")), \
             mock.patch.object(pipeline.time, "sleep", return_value=None):
            pipeline.main()

        self.assertEqual(order, ["seed", "scout", "fetch", "normalize", "gap"])


class SeedFactoryCriticalFixTests(unittest.TestCase):
    def test_failed_llm_generation_preserves_existing_seed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            self.addCleanup(os.chdir, cwd)
            seed_path = Path("seed_topics.txt")
            original = "# Existing\ncrm software\n"
            seed_path.write_text(original, encoding="utf-8")

            with mock.patch.object(sys, "argv", ["seed_factory.py", "--source", "llm", "--topic", "crm"]), \
                 mock.patch.object(seed_factory.requests, "post", side_effect=RuntimeError("ollama down")):
                with self.assertRaises(SystemExit) as cm:
                    seed_factory.main()

            self.assertNotEqual(cm.exception.code, 0)
            self.assertEqual(seed_path.read_text(encoding="utf-8"), original)


class GapAnalysisCriticalFixTests(unittest.TestCase):
    def test_png_output_keeps_json_and_visualization_separate(self):
        import gap_analysis

        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "normalized.jsonl"
            input_path.write_text(
                json.dumps({
                    "title": "ticket transfer ticket transfer resale fees",
                    "summary": "resale fees transfer delays resale fees transfer delays",
                    "comments": [],
                }) + "\n",
                encoding="utf-8",
            )
            output_path = Path(tmp) / "gaps.png"

            with mock.patch.object(sys, "argv", [
                "gap_analysis.py",
                "--input", str(input_path),
                "--output", str(output_path),
                "--viz",
                "--min-degree", "1",
            ]), \
                mock.patch.object(gap_analysis, "visualize") as fake_visualize, \
                redirect_stdout(io.StringIO()):
                gap_analysis.main()

            json_path = Path(tmp) / "gaps.json"
            self.assertTrue(json_path.exists())
            with json_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            self.assertEqual(payload["total_posts"], 1)
            fake_visualize.assert_called_once()
            self.assertEqual(fake_visualize.call_args.args[2], output_path)


if __name__ == "__main__":
    unittest.main()
