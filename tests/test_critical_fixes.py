import contextlib
import datetime
import importlib
import io
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


@contextlib.contextmanager
def temporary_cwd(path):
    old_cwd = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_cwd)


class PipelineCriticalFixTests(unittest.TestCase):
    def test_full_run_executes_downstream_phases_after_state_updates(self):
        import pipeline

        calls = []

        def mark_phase(name):
            def phase(args, run_id, state):
                calls.append(name)
                state[name] = "done"
                pipeline.save_run_state(run_id, state)
            return phase

        argv = [
            "pipeline.py",
            "--run_id",
            "unit_dynamic",
            "--keywords",
            "crm tools",
            "--skip_gap",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(pipeline, "DATA", tmp_path / "data"), \
                mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                mock.patch.object(pipeline, "run_phase_seed", mark_phase("seed")), \
                mock.patch.object(pipeline, "run_phase_scout", mark_phase("scout")), \
                mock.patch.object(pipeline, "run_phase_fetch", mark_phase("fetch")), \
                mock.patch.object(pipeline, "run_phase_normalize", mark_phase("normalize")), \
                mock.patch.object(sys, "argv", argv):
                pipeline.main()

        self.assertEqual(calls, ["scout", "fetch", "normalize"])

    def test_fetch_uses_argv_keywords_prefix_seen_and_scouted_subs(self):
        import pipeline

        captured = []

        def fake_run(cmd, label, check=True):
            captured.append(cmd)
            return types.SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            seed_file = tmp_path / "seed_topics.txt"
            seed_file.write_text("crm tools\nsales automation\n", encoding="utf-8")
            runs = tmp_path / "runs"
            data = tmp_path / "data"
            scout_file = runs / "unit_fetch" / "scouted_subreddits.json"
            scout_file.parent.mkdir(parents=True)
            scout_file.write_text('["CRMSoftware", "sales"]', encoding="utf-8")
            args = types.SimpleNamespace(
                run_id="unit_fetch",
                subs=None,
                keywords=None,
                niche_type="saas",
                max_posts=5,
                max_seeds=2,
                prefix="best",
                only_pain_points=True,
            )
            state = {}

            with mock.patch.object(pipeline, "SEED_FILE", seed_file), \
                mock.patch.object(pipeline, "RUNS", runs), \
                mock.patch.object(pipeline, "DATA", data), \
                mock.patch.object(pipeline, "run", fake_run):
                pipeline.run_phase_fetch(args, args.run_id, state)

        cmd = captured[0]
        self.assertIsInstance(cmd, list)
        self.assertNotIn("shell=True", " ".join(cmd))
        self.assertEqual(cmd[cmd.index("--subs") + 1], "CRMSoftware,sales")
        self.assertEqual(cmd[cmd.index("--keywords") + 1], "crm tools,sales automation")
        self.assertEqual(cmd[cmd.index("--prefix") + 1], "best")
        self.assertEqual(cmd[cmd.index("--seen") + 1], str(data / "unit_fetch_seen_post_ids.txt"))
        self.assertIn("--only_pain_points", cmd)
        self.assertEqual(state["fetch"], "done")

    def test_fetch_without_subs_or_scout_output_fails(self):
        import pipeline

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            seed_file = tmp_path / "seed_topics.txt"
            seed_file.write_text("crm tools\n", encoding="utf-8")
            args = types.SimpleNamespace(
                run_id="unit_missing_scout",
                subs=None,
                keywords=None,
                niche_type="saas",
                max_posts=5,
                max_seeds=2,
                prefix=None,
                only_pain_points=False,
            )
            state = {}

            with mock.patch.object(pipeline, "SEED_FILE", seed_file), \
                mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                mock.patch.object(pipeline, "DATA", tmp_path / "data"), \
                mock.patch.object(pipeline, "run") as run_mock:
                with self.assertRaises(SystemExit) as raised:
                    pipeline.run_phase_fetch(args, args.run_id, state)

        self.assertNotEqual(raised.exception.code, 0)
        self.assertNotIn("fetch", state)
        run_mock.assert_not_called()

    def test_failed_scout_does_not_mark_state_done(self):
        import pipeline

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            args = types.SimpleNamespace(keywords="crm tools", max_seeds=3)
            state = {}

            with mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                mock.patch.object(pipeline, "run", side_effect=SystemExit(1)):
                with self.assertRaises(SystemExit):
                    pipeline.run_phase_scout(args, "unit_scout", state)

        self.assertNotIn("scout", state)

    def test_generated_run_id_includes_time(self):
        import pipeline

        args = types.SimpleNamespace(topic="CRM Tools", niche_type="saas")

        run_id = pipeline.generate_run_id(
            args,
            now=datetime.datetime(2026, 7, 1, 11, 2, 3),
        )

        self.assertEqual(run_id, "20260701_110203_crm_tools")


class SeedFactoryCriticalFixTests(unittest.TestCase):
    def test_llm_failure_preserves_existing_seed_file(self):
        import seed_factory

        with tempfile.TemporaryDirectory() as tmp:
            seed_path = Path(tmp) / "seed_topics.txt"
            original = "# existing\ncrm tools\n"
            seed_path.write_text(original, encoding="utf-8")
            argv = [
                "seed_factory.py",
                "--source",
                "llm",
                "--topic",
                "crm",
                "--count",
                "3",
            ]

            with temporary_cwd(tmp), \
                mock.patch.object(sys, "argv", argv), \
                mock.patch.object(seed_factory.requests, "post", side_effect=RuntimeError("ollama down")):
                with self.assertRaises(SystemExit) as raised:
                    seed_factory.main()

            self.assertNotEqual(raised.exception.code, 0)
            self.assertEqual(seed_path.read_text(encoding="utf-8"), original)


class RssMinerCriticalFixTests(unittest.TestCase):
    def test_cli_keywords_do_not_require_seed_file_for_urls(self):
        import rss_miner

        argv = [
            "rss_miner.py",
            "--mode",
            "urls",
            "--niche_type",
            "saas",
            "--subs",
            "CRMSoftware",
            "--include_search",
            "--keywords",
            "crm tools,sales automation",
            "--max_keywords",
            "1",
        ]

        with tempfile.TemporaryDirectory() as tmp, temporary_cwd(tmp), \
            mock.patch.object(sys, "argv", argv), \
            mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            rss_miner.main()

        output = stdout.getvalue()
        self.assertIn("Total URLs:", output)
        self.assertIn("crm+tools", output)
        self.assertNotIn("sales+automation", output)

    def test_search_without_keywords_fails(self):
        import rss_miner

        argv = [
            "rss_miner.py",
            "--mode",
            "urls",
            "--include_search",
            "--subs",
            "CRMSoftware",
        ]

        with tempfile.TemporaryDirectory() as tmp, temporary_cwd(tmp), \
            mock.patch.object(sys, "argv", argv):
            with self.assertRaises(SystemExit) as raised:
                rss_miner.main()

        self.assertNotEqual(raised.exception.code, 0)


class GapAnalysisCriticalFixTests(unittest.TestCase):
    def test_empty_input_exits_nonzero(self):
        import gap_analysis

        with tempfile.TemporaryDirectory() as tmp:
            empty_input = Path(tmp) / "empty.jsonl"
            empty_input.write_text("", encoding="utf-8")
            argv = ["gap_analysis.py", "--input", str(empty_input)]

            with mock.patch.object(sys, "argv", argv):
                with self.assertRaises(SystemExit) as raised:
                    gap_analysis.main()

        self.assertNotEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
