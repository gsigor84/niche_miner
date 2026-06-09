import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pipeline
import seed_factory


class PipelineCriticalFixTests(unittest.TestCase):
    def test_fresh_pipeline_runs_downstream_phases_after_seed_and_scout(self):
        calls = []

        def mark_done(phase):
            def _runner(args, run_id, state):
                calls.append(phase)
                state[phase] = "done"
            return _runner

        argv = [
            "pipeline.py",
            "--run_id",
            "unit_run",
            "--topic",
            "crm software",
            "--niche_type",
            "saas",
            "--skip_gap",
        ]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(pipeline, "run_phase_seed", mark_done("seed")), \
             mock.patch.object(pipeline, "run_phase_scout", mark_done("scout")), \
             mock.patch.object(pipeline, "run_phase_fetch", mark_done("fetch")), \
             mock.patch.object(pipeline, "run_phase_normalize", mark_done("normalize")):
            pipeline.main()

        self.assertEqual(calls, ["seed", "scout", "fetch", "normalize"])

    def test_normalize_phase_does_not_require_only_pain_points_arg(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir()
            (data_dir / "unit_raw.jsonl").write_text("{}\n", encoding="utf-8")
            args = SimpleNamespace(run_id="unit")
            state = {}

            with mock.patch.object(pipeline, "DATA", data_dir), \
                 mock.patch.object(pipeline, "save_run_state"), \
                 mock.patch.object(pipeline, "run") as run_mock:
                pipeline.run_phase_normalize(args, "unit", state)

            cmd = run_mock.call_args.args[0]
            self.assertNotIn("--only_pain_points", cmd)
            self.assertEqual(state["normalize"], "done")

    def test_fetch_uses_argv_and_forwards_untrusted_values_as_arguments(self):
        args = SimpleNamespace(
            niche_type="saas",
            subs="CRM; touch /tmp/pwned",
            max_posts=1,
            prefix="best; echo unsafe",
            keywords="crm software; echo unsafe",
            max_seeds=3,
            only_pain_points=True,
        )
        state = {}

        with mock.patch.object(pipeline, "save_run_state"), \
             mock.patch.object(pipeline.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run_mock:
            pipeline.run_phase_fetch(args, "unit", state)

        cmd = run_mock.call_args.args[0]
        kwargs = run_mock.call_args.kwargs
        self.assertIsInstance(cmd, list)
        self.assertNotEqual(kwargs.get("shell"), True)
        self.assertIn("CRM; touch /tmp/pwned", cmd)
        self.assertIn("crm software; echo unsafe", cmd)
        self.assertIn("--keywords", cmd)
        self.assertIn("--seen", cmd)
        self.assertEqual(state["fetch"], "done")

    def test_scout_subs_are_parsed_for_fetch_handoff(self):
        output = "\n[SUCCESS] Top discovered subreddits: CRM,Sales\nTo use with rss_miner: --subs CRM,Sales\n"

        self.assertEqual(pipeline.parse_scout_subs(output), "CRM,Sales")


class SeedFactoryCriticalFixTests(unittest.TestCase):
    def test_failed_llm_generation_preserves_existing_seed_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            seed_path = Path(tmpdir) / "seed_topics.txt"
            seed_path.write_text("existing seed\n", encoding="utf-8")
            argv = ["seed_factory.py", "--source", "llm", "--topic", "crm"]

            with mock.patch.object(sys, "argv", argv), \
                 mock.patch.object(seed_factory, "OUTPUT_FILE", str(seed_path)), \
                 mock.patch.object(seed_factory.requests, "post", side_effect=RuntimeError("offline")):
                with self.assertRaises(SystemExit) as raised:
                    seed_factory.main()

            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(seed_path.read_text(encoding="utf-8"), "existing seed\n")


if __name__ == "__main__":
    unittest.main()
