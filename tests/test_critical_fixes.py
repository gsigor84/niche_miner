import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipeline
import seed_factory


class PipelineCriticalFixTests(unittest.TestCase):
    def make_args(self, tmpdir, **overrides):
        defaults = {
            "run_id": "critical_probe",
            "resume": False,
            "phase": None,
            "keywords": None,
            "topic": "crm tools",
            "niche_type": "saas",
            "prefix": None,
            "subs": None,
            "skip_seed": False,
            "skip_scout": False,
            "skip_gap": False,
            "seed_count": 3,
            "max_seeds": 5,
            "max_posts": 2,
            "only_pain_points": False,
            "top_gaps": 10,
            "min_degree": 2,
            "viz": False,
            "input": None,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_fresh_pipeline_runs_all_downstream_phases(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            data = project / "data"
            runs = project / "runs"
            args = self.make_args(tmp)
            calls = []

            def fake_phase(name):
                def _run(_args, run_id, state):
                    calls.append(name)
                    state[name] = "done"
                    pipeline.save_run_state(run_id, state)
                return _run

            with mock.patch.object(pipeline, "PROJECT", project), \
                 mock.patch.object(pipeline, "DATA", data), \
                 mock.patch.object(pipeline, "RUNS", runs), \
                 mock.patch.object(pipeline, "SEED_FILE", project / "seed_topics.txt"), \
                 mock.patch.object(pipeline, "parse_args", return_value=args), \
                 mock.patch.object(pipeline, "run_phase_seed", fake_phase("seed")), \
                 mock.patch.object(pipeline, "run_phase_scout", fake_phase("scout")), \
                 mock.patch.object(pipeline, "run_phase_fetch", fake_phase("fetch")), \
                 mock.patch.object(pipeline, "run_phase_normalize", fake_phase("normalize")), \
                 mock.patch.object(pipeline, "run_phase_gap", fake_phase("gap")), \
                 mock.patch.object(pipeline.time, "sleep", return_value=None):
                pipeline.main()

            self.assertEqual(calls, ["seed", "scout", "fetch", "normalize", "gap"])

    def test_scout_invokes_subprocess_without_shell_splitting_keywords(self):
        args = self.make_args(
            tempfile.gettempdir(),
            keywords="crm software,sales automation",
            subs=None,
        )
        state = {}
        completed = SimpleNamespace(
            returncode=0,
            stdout="\n[SUCCESS] Top discovered subreddits: CRMSoftware\nTo use with rss_miner: --subs CRMSoftware,CRM\n",
            stderr="",
        )

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(pipeline, "PROJECT", Path(tmp)), \
             mock.patch.object(pipeline, "RUNS", Path(tmp) / "runs"), \
             mock.patch.object(pipeline.subprocess, "run", return_value=completed) as run_mock:
            pipeline.run_phase_scout(args, args.run_id, state)

        cmd = run_mock.call_args.args[0]
        self.assertEqual(cmd[:3], ["python3", "scout_subreddits.py", "crm software,sales automation"])
        self.assertFalse(run_mock.call_args.kwargs.get("shell", False))
        self.assertEqual(state["subs"], "CRMSoftware,CRM")
        self.assertEqual(state["scout"], "done")

    def test_fetch_forwards_cli_keywords_and_uses_run_scoped_seen_file(self):
        args = self.make_args(
            tempfile.gettempdir(),
            keywords="crm software,sales automation",
            prefix="best",
            subs=None,
            only_pain_points=True,
        )
        state = {"subs": "CRMSoftware,CRM"}
        completed = SimpleNamespace(returncode=0, stdout="Done.\n", stderr="")

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(pipeline, "PROJECT", Path(tmp)), \
             mock.patch.object(pipeline, "RUNS", Path(tmp) / "runs"), \
             mock.patch.object(pipeline.subprocess, "run", return_value=completed) as run_mock:
            pipeline.run_phase_fetch(args, args.run_id, state)

        cmd = run_mock.call_args.args[0]
        self.assertIn("--keywords", cmd)
        self.assertEqual(cmd[cmd.index("--keywords") + 1], "crm software,sales automation")
        self.assertIn("--prefix", cmd)
        self.assertEqual(cmd[cmd.index("--prefix") + 1], "best")
        self.assertIn("--seen", cmd)
        self.assertEqual(cmd[cmd.index("--seen") + 1], "data/critical_probe_seen_post_ids.txt")
        self.assertIn("--only_pain_points", cmd)
        self.assertEqual(state["fetch"], "done")


class SeedFactoryCriticalFixTests(unittest.TestCase):
    def test_failed_generation_does_not_overwrite_existing_seed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_path = Path(tmp) / "seed_topics.txt"
            original = "# existing\ncrm software\n"
            seed_path.write_text(original, encoding="utf-8")
            old_cwd = os.getcwd()
            os.chdir(tmp)
            try:
                with mock.patch.object(sys, "argv", ["seed_factory.py", "--source", "llm", "--topic", "crm"]), \
                     mock.patch.object(seed_factory.requests, "post", side_effect=RuntimeError("ollama down")):
                    with self.assertRaises(SystemExit) as raised:
                        seed_factory.main()
                self.assertNotEqual(raised.exception.code, 0)
                self.assertEqual(seed_path.read_text(encoding="utf-8"), original)
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
