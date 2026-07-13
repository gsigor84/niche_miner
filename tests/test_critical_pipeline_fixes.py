import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pipeline


class CriticalPipelineFixTests(unittest.TestCase):
    def make_args(self, **overrides):
        args = SimpleNamespace(
            run_id="critical_run",
            topic="crm tools",
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
        for key, value in overrides.items():
            setattr(args, key, value)
        return args

    def test_fresh_pipeline_runs_downstream_phases_after_seed_and_scout(self):
        args = self.make_args()
        calls = []

        def phase(name):
            def run(args, run_id, state):
                calls.append(name)
                state[name] = "done"
            return run

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            with mock.patch.object(pipeline, "DATA", tmp / "data"), \
                    mock.patch.object(pipeline, "RUNS", tmp / "runs"), \
                    mock.patch.object(pipeline, "parse_args", return_value=args), \
                    mock.patch.object(pipeline, "run_phase_seed", phase("seed")), \
                    mock.patch.object(pipeline, "run_phase_scout", phase("scout")), \
                    mock.patch.object(pipeline, "run_phase_fetch", phase("fetch")), \
                    mock.patch.object(pipeline, "run_phase_normalize", phase("normalize")), \
                    mock.patch.object(pipeline, "run_phase_gap", phase("gap")), \
                    contextlib.redirect_stdout(io.StringIO()):
                pipeline.main()

        self.assertEqual(calls, ["seed", "scout", "fetch", "normalize", "gap"])

    def test_normalize_phase_does_not_require_only_pain_points_arg(self):
        args = self.make_args()

        with tempfile.TemporaryDirectory() as tmpdir:
            data = Path(tmpdir) / "data"
            data.mkdir()
            (data / "critical_run_raw.jsonl").write_text('{"title": "ok"}\n', encoding="utf-8")
            state = {}

            with mock.patch.object(pipeline, "DATA", data), \
                    mock.patch.object(pipeline, "run") as run:
                pipeline.run_phase_normalize(args, args.run_id, state)

        cmd = run.call_args.args[0]
        self.assertNotIn("--only_pain_points", cmd)
        self.assertEqual(state["normalize"], "done")

    def test_single_phase_preserves_existing_run_state(self):
        args = self.make_args(phase="normalize")
        existing_state = {"seed": "done", "scout": "done", "fetch": "done"}
        seen_states = []

        def normalize(args, run_id, state):
            state["normalize"] = "done"
            seen_states.append(dict(state))

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            with mock.patch.object(pipeline, "DATA", tmp / "data"), \
                    mock.patch.object(pipeline, "RUNS", tmp / "runs"), \
                    mock.patch.object(pipeline, "parse_args", return_value=args), \
                    mock.patch.object(pipeline, "load_run_state", return_value=dict(existing_state)), \
                    mock.patch.object(pipeline, "run_phase_normalize", normalize), \
                    contextlib.redirect_stdout(io.StringIO()), \
                    self.assertRaises(SystemExit):
                pipeline.main()

        self.assertEqual(
            seen_states,
            [{"seed": "done", "scout": "done", "fetch": "done", "normalize": "done"}],
        )

    def test_scout_persists_discovered_subreddits_and_uses_argv(self):
        args = self.make_args(keywords="crm tools,sales automation")
        result = SimpleNamespace(
            returncode=0,
            stdout="\n[SUCCESS] Top discovered subreddits: CRMSoftware, CRM\n"
                   "To use with rss_miner: --subs CRMSoftware,CRM\n",
        )
        state = {}

        with mock.patch.object(pipeline.subprocess, "run", return_value=result) as run, \
                mock.patch.object(pipeline, "save_run_state"), \
                contextlib.redirect_stdout(io.StringIO()):
            pipeline.run_phase_scout(args, args.run_id, state)

        cmd = run.call_args.args[0]
        self.assertIsInstance(cmd, list)
        self.assertIn("crm tools,sales automation", cmd)
        self.assertEqual(state["discovered_subs"], ["CRMSoftware", "CRM"])
        self.assertEqual(state["scout"], "done")

    def test_fetch_uses_discovered_subs_keywords_and_run_scoped_seen_file(self):
        args = self.make_args(keywords="crm tools", prefix="best")
        state = {"discovered_subs": ["CRMSoftware", "CRM"]}

        with tempfile.TemporaryDirectory() as tmpdir:
            data = Path(tmpdir) / "data"
            data.mkdir()

            def fake_run(cmd, **kwargs):
                out_path = Path(cmd[cmd.index("--out") + 1])
                out_path.write_text('{"post_id": "abc123"}\n', encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="saved: abc123\n")

            with mock.patch.object(pipeline, "DATA", data), \
                    mock.patch.object(pipeline.subprocess, "run", side_effect=fake_run) as run, \
                    mock.patch.object(pipeline, "save_run_state"), \
                    contextlib.redirect_stdout(io.StringIO()):
                pipeline.run_phase_fetch(args, args.run_id, state)

        cmd = run.call_args.args[0]
        self.assertIsInstance(cmd, list)
        self.assertEqual(cmd[cmd.index("--subs") + 1], "CRMSoftware,CRM")
        self.assertEqual(cmd[cmd.index("--keywords") + 1], "crm tools")
        self.assertEqual(cmd[cmd.index("--prefix") + 1], "best")
        self.assertTrue(cmd[cmd.index("--seen") + 1].endswith("critical_run_seen_post_ids.txt"))
        self.assertEqual(state["fetch"], "done")

    def test_fetch_failure_does_not_mark_state_done(self):
        args = self.make_args(subs="CRMSoftware")
        state = {}
        result = SimpleNamespace(returncode=1, stdout="boom\n")

        with mock.patch.object(pipeline.subprocess, "run", return_value=result), \
                mock.patch.object(pipeline, "save_run_state") as save_run_state, \
                contextlib.redirect_stdout(io.StringIO()), \
                self.assertRaises(SystemExit):
            pipeline.run_phase_fetch(args, args.run_id, state)

        self.assertNotIn("fetch", state)
        save_run_state.assert_not_called()


if __name__ == "__main__":
    unittest.main()
