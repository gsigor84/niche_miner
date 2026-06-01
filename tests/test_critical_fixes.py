import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipeline
import seed_factory


class PipelineCriticalFixTests(unittest.TestCase):
    def make_args(self, **overrides):
        defaults = {
            "run_id": "critical_run",
            "topic": None,
            "keywords": None,
            "niche_type": "saas",
            "prefix": None,
            "subs": None,
            "seed_count": 5,
            "max_seeds": 3,
            "max_posts": 10,
            "top_gaps": 20,
            "min_degree": 2,
            "viz": False,
            "input": None,
            "skip_seed": False,
            "skip_scout": False,
            "skip_gap": False,
            "only_pain_points": False,
        }
        defaults.update(overrides)
        return types.SimpleNamespace(**defaults)

    def test_full_pipeline_runs_downstream_phases_after_state_updates(self):
        args = self.make_args()
        state = {}
        calls = []

        def phase(name):
            def _run(_args, _run_id, state_obj):
                calls.append(name)
                state_obj[name] = "done"
            return _run

        with mock.patch.object(pipeline, "save_run_state"), \
             mock.patch.object(pipeline, "run_phase_seed", phase("seed")), \
             mock.patch.object(pipeline, "run_phase_scout", phase("scout")), \
             mock.patch.object(pipeline, "run_phase_fetch", phase("fetch")), \
             mock.patch.object(pipeline, "run_phase_normalize", phase("normalize")), \
             mock.patch.object(pipeline, "run_phase_gap", phase("gap")):
            phases = pipeline.run_sequential_pipeline(args, state)

        self.assertEqual(phases, ["seed", "scout", "fetch", "normalize", "gap"])
        self.assertEqual(calls, phases)

    def test_fetch_preserves_keywords_and_uses_run_scoped_seen_file(self):
        args = self.make_args(
            keywords="crm tools,sales automation",
            prefix="best",
            subs="CRMSoftware,CRM",
            only_pain_points=True,
        )
        state = {}
        captured = {}

        def fake_run(cmd, label):
            captured["cmd"] = cmd
            captured["label"] = label

        with mock.patch.object(pipeline, "run", side_effect=fake_run), \
             mock.patch.object(pipeline, "save_run_state"):
            pipeline.run_phase_fetch(args, args.run_id, state)

        cmd = captured["cmd"]
        self.assertIn("--keywords", cmd)
        self.assertEqual(cmd[cmd.index("--keywords") + 1], "crm tools,sales automation")
        self.assertIn("--prefix", cmd)
        self.assertEqual(cmd[cmd.index("--prefix") + 1], "best")
        self.assertIn("--seen", cmd)
        self.assertEqual(cmd[cmd.index("--seen") + 1], "data/critical_run_seen_post_ids.txt")
        self.assertIn("--only_pain_points", cmd)
        self.assertEqual(state["fetch"], "done")

    def test_scout_failure_does_not_mark_phase_done(self):
        args = self.make_args(keywords="crm tools")
        state = {}
        failed = types.SimpleNamespace(returncode=1, stdout="", stderr="network down")

        with mock.patch.object(pipeline.subprocess, "run", return_value=failed), \
             mock.patch.object(pipeline, "save_run_state"):
            with self.assertRaises(SystemExit):
                pipeline.run_phase_scout(args, args.run_id, state)

        self.assertNotIn("scout", state)


class SeedFactoryCriticalFixTests(unittest.TestCase):
    def test_failed_generation_leaves_existing_seed_file_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                seed_file = Path("seed_topics.txt")
                original = "# Existing\ncrm tools\n"
                seed_file.write_text(original, encoding="utf-8")

                with mock.patch.object(sys, "argv", [
                    "seed_factory.py",
                    "--source", "llm",
                    "--topic", "crm",
                    "--append",
                ]), mock.patch.object(seed_factory.SeedFactory, "brainstorm_llm", return_value=None):
                    with self.assertRaises(SystemExit) as ctx:
                        seed_factory.main()

                self.assertNotEqual(ctx.exception.code, 0)
                self.assertEqual(seed_file.read_text(encoding="utf-8"), original)
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
