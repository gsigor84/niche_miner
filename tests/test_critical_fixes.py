import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipeline
import seed_factory


class PipelineCriticalFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.original_globals = {
            "PROJECT": pipeline.PROJECT,
            "DATA": pipeline.DATA,
            "RUNS": pipeline.RUNS,
            "SEED_FILE": pipeline.SEED_FILE,
        }
        pipeline.PROJECT = self.root
        pipeline.DATA = self.root / "data"
        pipeline.RUNS = self.root / "runs"
        pipeline.SEED_FILE = self.root / "seed_topics.txt"
        pipeline.DATA.mkdir()
        pipeline.RUNS.mkdir()

    def tearDown(self):
        for name, value in self.original_globals.items():
            setattr(pipeline, name, value)
        self.tmp.cleanup()

    def test_fresh_full_run_executes_downstream_phases_after_state_updates(self):
        calls = []

        def fake_phase(name):
            def _run(args, run_id, state):
                calls.append(name)
                state[name] = "done"
                pipeline.save_run_state(run_id, state)
            return _run

        with patch.object(sys, "argv", ["pipeline.py", "--run_id", "full_dynamic"]), \
             patch.object(pipeline, "run_phase_seed", fake_phase("seed")), \
             patch.object(pipeline, "run_phase_scout", fake_phase("scout")), \
             patch.object(pipeline, "run_phase_fetch", fake_phase("fetch")), \
             patch.object(pipeline, "run_phase_normalize", fake_phase("normalize")), \
             patch.object(pipeline, "run_phase_gap", fake_phase("gap")), \
             patch.object(pipeline.time, "sleep", lambda _: None):
            pipeline.main()

        self.assertEqual(calls, ["seed", "scout", "fetch", "normalize", "gap"])

    def test_normalize_phase_does_not_reference_fetch_only_flags(self):
        run_id = "normal_run"
        raw = pipeline.DATA / f"{run_id}_raw.jsonl"
        raw.write_text("{}\n", encoding="utf-8")
        args = SimpleNamespace(run_id=run_id)
        state = {}

        with patch.object(pipeline, "run") as run_mock:
            pipeline.run_phase_normalize(args, run_id, state)

        cmd = run_mock.call_args.args[0]
        self.assertNotIn("--only_pain_points", cmd)
        self.assertEqual(state["normalize"], "done")

    def test_scout_uses_argv_and_persists_discovered_subreddits(self):
        args = SimpleNamespace(
            keywords="crm tools,sales automation",
            max_seeds=5,
            subs=None,
        )
        state = {}
        result = SimpleNamespace(
            returncode=0,
            stdout="\n[SUCCESS] Top discovered subreddits: CRM, sales\nTo use with rss_miner: --subs CRM,sales\n",
        )

        with patch.object(pipeline.subprocess, "run", return_value=result) as run_mock:
            pipeline.run_phase_scout(args, "scout_run", state)

        cmd = run_mock.call_args.args[0]
        kwargs = run_mock.call_args.kwargs
        self.assertIsInstance(cmd, list)
        self.assertEqual(cmd[2], "crm tools,sales automation")
        self.assertFalse(kwargs.get("shell", False))
        self.assertEqual(state["subs"], ["CRM", "sales"])
        self.assertEqual(state["scout"], "done")

    def test_fetch_forwards_keywords_subs_seen_file_and_pain_filter(self):
        args = SimpleNamespace(
            run_id="fetch_run",
            niche_type="saas",
            max_posts=10,
            subs=None,
            prefix="best",
            keywords="crm tools,sales automation",
            only_pain_points=True,
        )
        state = {"subs": ["CRM", "sales"]}

        with patch.object(pipeline, "run") as run_mock:
            pipeline.run_phase_fetch(args, "fetch_run", state)

        cmd = run_mock.call_args.args[0]
        self.assertIn("--keywords", cmd)
        self.assertEqual(cmd[cmd.index("--keywords") + 1], "crm tools,sales automation")
        self.assertEqual(cmd[cmd.index("--subs") + 1], "CRM,sales")
        self.assertEqual(cmd[cmd.index("--seen") + 1], "data/fetch_run_seen_post_ids.txt")
        self.assertEqual(cmd[cmd.index("--prefix") + 1], "best")
        self.assertIn("--only_pain_points", cmd)
        self.assertEqual(state["fetch"], "done")

    def test_gap_failure_is_not_marked_done(self):
        run_id = "gap_run"
        normalized = pipeline.DATA / f"{run_id}_normalized.jsonl"
        normalized.write_text("{}\n", encoding="utf-8")
        args = SimpleNamespace(
            input=None,
            run_id=run_id,
            top_gaps=20,
            min_degree=3,
            viz=False,
        )
        state = {}

        def fail_when_checked(cmd, label, check=True):
            if check:
                raise SystemExit(1)

        with patch.object(pipeline, "run", fail_when_checked):
            with self.assertRaises(SystemExit):
                pipeline.run_phase_gap(args, run_id, state)

        self.assertNotIn("gap", state)


class SeedFactoryCriticalFixTests(unittest.TestCase):
    def test_failed_llm_generation_preserves_existing_seed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_path = Path(tmp) / "seed_topics.txt"
            original = "# existing seeds\nexisting crm\n"
            seed_path.write_text(original, encoding="utf-8")
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                with patch.object(sys, "argv", ["seed_factory.py", "--source", "llm", "--topic", "crm"]), \
                     patch.object(seed_factory.SeedFactory, "brainstorm_llm", lambda *args, **kwargs: None):
                    exit_code = seed_factory.main()
            finally:
                os.chdir(old_cwd)

            self.assertEqual(exit_code, 1)
            self.assertEqual(seed_path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
