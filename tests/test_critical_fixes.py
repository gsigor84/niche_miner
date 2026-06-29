import argparse
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pipeline
import seed_factory


class PipelineCriticalFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.runs = self.root / "runs"
        self.seed_file = self.root / "seed_topics.txt"
        self.seed_file.write_text("crm tools\nsales automation\n", encoding="utf-8")
        self.patches = [
            mock.patch.object(pipeline, "PROJECT", self.root),
            mock.patch.object(pipeline, "DATA", self.data),
            mock.patch.object(pipeline, "RUNS", self.runs),
            mock.patch.object(pipeline, "SEED_FILE", self.seed_file),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def args(self, **overrides):
        values = dict(
            run_id="critical_run",
            topic="CRM tools",
            keywords=None,
            niche_type="saas",
            prefix=None,
            subs=None,
            resume=False,
            phase=None,
            seed_count=5,
            max_seeds=3,
            max_posts=10,
            top_gaps=20,
            min_degree=3,
            viz=False,
            input=None,
            skip_seed=False,
            skip_gap=False,
            skip_scout=False,
        )
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_full_run_executes_downstream_phases_without_resume(self):
        order = []

        def phase(name):
            def _run(args, run_id, state):
                order.append(name)
                state[name] = "done"
                pipeline.save_run_state(run_id, state)
            return _run

        with mock.patch.object(pipeline, "parse_args", return_value=self.args()), \
             mock.patch.object(pipeline, "run_phase_seed", phase("seed")), \
             mock.patch.object(pipeline, "run_phase_scout", phase("scout")), \
             mock.patch.object(pipeline, "run_phase_fetch", phase("fetch")), \
             mock.patch.object(pipeline, "run_phase_normalize", phase("normalize")), \
             mock.patch.object(pipeline, "run_phase_gap", phase("gap")), \
             mock.patch.object(pipeline.time, "sleep"):
            pipeline.main()

        self.assertEqual(order, ["seed", "scout", "fetch", "normalize", "gap"])

    def test_single_phase_preserves_existing_state(self):
        state_file = self.runs / "critical_run" / "state.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text(json.dumps({"seed": "done", "scout": "done"}), encoding="utf-8")

        def run_gap(args, run_id, state):
            state["gap"] = "done"
            pipeline.save_run_state(run_id, state)

        with mock.patch.object(pipeline, "parse_args", return_value=self.args(phase="gap")), \
             mock.patch.object(pipeline, "run_phase_gap", run_gap), \
             self.assertRaises(SystemExit) as exit_ctx:
            pipeline.main()

        self.assertEqual(exit_ctx.exception.code, 0)
        saved = json.loads(state_file.read_text(encoding="utf-8"))
        self.assertEqual(saved["seed"], "done")
        self.assertEqual(saved["scout"], "done")
        self.assertEqual(saved["gap"], "done")

    def test_fetch_uses_safe_argv_and_run_scoped_inputs(self):
        args = self.args(keywords="crm tools,sales automation", prefix="best")
        state = {"discovered_subs": ["CRMSoftware", "sales"]}
        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            raw_path = self.data / "critical_run_raw.jsonl"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text('{"post_id":"abc123"}\n', encoding="utf-8")
            return argparse.Namespace(returncode=0, stdout="saved", stderr="")

        with mock.patch.object(pipeline.subprocess, "run", side_effect=fake_run):
            pipeline.run_phase_fetch(args, args.run_id, state)

        cmd = captured["cmd"]
        self.assertIsInstance(cmd, list)
        self.assertNotIn("shell", captured["kwargs"])
        self.assertEqual(cmd[cmd.index("--subs") + 1], "CRMSoftware,sales")
        self.assertEqual(cmd[cmd.index("--keywords") + 1], "crm tools,sales automation")
        self.assertEqual(cmd[cmd.index("--prefix") + 1], "best")
        self.assertEqual(cmd[cmd.index("--seen") + 1], str(self.data / "critical_run_seen_post_ids.txt"))
        self.assertEqual(state["fetch"], "done")


class SeedFactoryCriticalFixTests(unittest.TestCase):
    def test_failed_generation_preserves_existing_seed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                seed_path = Path("seed_topics.txt")
                original = "# Existing seeds\ncrm tools\n"
                seed_path.write_text(original, encoding="utf-8")

                with mock.patch.object(seed_factory.sys, "argv", [
                    "seed_factory.py", "--source", "llm", "--topic", "CRM"
                ]), \
                     mock.patch.object(seed_factory.SeedFactory, "brainstorm_llm", return_value=None), \
                     self.assertRaises(SystemExit) as exit_ctx:
                    seed_factory.main()

                self.assertEqual(exit_ctx.exception.code, 1)
                self.assertEqual(seed_path.read_text(encoding="utf-8"), original)
            finally:
                os.chdir(original_cwd)


if __name__ == "__main__":
    unittest.main()
