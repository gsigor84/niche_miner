import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def install_optional_dependency_stubs():
    try:
        import feedparser  # noqa: F401
    except ImportError:
        feedparser_stub = types.ModuleType("feedparser")
        feedparser_stub.FeedParserDict = dict
        feedparser_stub.parse = lambda raw: SimpleNamespace(entries=[])
        sys.modules["feedparser"] = feedparser_stub

    try:
        import bs4  # noqa: F401
    except ImportError:
        bs4_stub = types.ModuleType("bs4")

        class BeautifulSoup:
            def __init__(self, html, parser):
                self.html = html

            def get_text(self, separator=" ", strip=False):
                text = self.html or ""
                return text.strip() if strip else text

        bs4_stub.BeautifulSoup = BeautifulSoup
        sys.modules["bs4"] = bs4_stub


install_optional_dependency_stubs()

import pipeline
import rss_miner
import seed_factory


class CriticalPipelineFixTests(unittest.TestCase):
    def with_pipeline_paths(self, temp_dir):
        patches = [
            patch.object(pipeline, "DATA", Path(temp_dir) / "data"),
            patch.object(pipeline, "RUNS", Path(temp_dir) / "runs"),
            patch.object(pipeline, "SEED_FILE", Path(temp_dir) / "seed_topics.txt"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_fresh_pipeline_runs_all_phases_from_updated_state(self):
        with tempfile.TemporaryDirectory() as td:
            self.with_pipeline_paths(td)
            calls = []

            args = SimpleNamespace(
                run_id="critical_run",
                topic="critical run",
                keywords=None,
                niche_type="saas",
                prefix=None,
                subs=None,
                resume=False,
                phase=None,
                seed_count=2,
                max_seeds=2,
                max_posts=1,
                top_gaps=5,
                min_degree=1,
                viz=False,
                input=None,
                skip_seed=False,
                skip_gap=False,
                skip_scout=False,
                only_pain_points=False,
            )

            def fake_phase(name):
                def _run(parsed_args, run_id, state):
                    calls.append(name)
                    pipeline.mark_phase_done(run_id, state, name)

                return _run

            with patch.object(pipeline, "parse_args", return_value=args), \
                    patch.object(pipeline, "run_phase_seed", fake_phase("seed")), \
                    patch.object(pipeline, "run_phase_scout", fake_phase("scout")), \
                    patch.object(pipeline, "run_phase_fetch", fake_phase("fetch")), \
                    patch.object(pipeline, "run_phase_normalize", fake_phase("normalize")), \
                    patch.object(pipeline, "run_phase_gap", fake_phase("gap")):
                pipeline.main()

            self.assertEqual(calls, ["seed", "scout", "fetch", "normalize", "gap"])
            state = json.loads((pipeline.RUNS / "critical_run" / "state.json").read_text())
            self.assertEqual({phase: state.get(phase) for phase in pipeline.PHASES},
                             {phase: "done" for phase in pipeline.PHASES})

    def test_scout_uses_argv_and_persists_discovered_subreddits(self):
        with tempfile.TemporaryDirectory() as td:
            self.with_pipeline_paths(td)
            pipeline.SEED_FILE.write_text("party tickets\ncrm tools\n", encoding="utf-8")
            args = SimpleNamespace(keywords=None, subs=None, max_seeds=20)
            captured = {}

            def fake_run(cmd, **kwargs):
                captured["cmd"] = cmd
                captured["kwargs"] = kwargs
                return SimpleNamespace(
                    returncode=0,
                    stdout="To use with rss_miner: --subs CRMSoftware,SalesOps\n",
                )

            with patch.object(pipeline.subprocess, "run", side_effect=fake_run):
                pipeline.run_phase_scout(args, "critical_run", {})

            self.assertIsInstance(captured["cmd"], list)
            self.assertNotIn("shell", captured["kwargs"])
            self.assertEqual(captured["cmd"][2], "party tickets,crm tools")
            self.assertEqual(
                (pipeline.RUNS / "critical_run" / "subreddits.txt").read_text(encoding="utf-8"),
                "CRMSoftware,SalesOps",
            )

    def test_fetch_uses_discovered_subs_run_scoped_seen_and_cli_keywords(self):
        with tempfile.TemporaryDirectory() as td:
            self.with_pipeline_paths(td)
            (pipeline.RUNS / "critical_run").mkdir(parents=True)
            (pipeline.RUNS / "critical_run" / "subreddits.txt").write_text("CRMSoftware,SalesOps", encoding="utf-8")
            args = SimpleNamespace(
                niche_type="saas",
                subs=None,
                max_posts=3,
                prefix="best",
                keywords="crm tools,sales automation",
                only_pain_points=True,
            )
            captured = {}

            def fake_run(cmd, **kwargs):
                captured["cmd"] = cmd
                captured["kwargs"] = kwargs
                return SimpleNamespace(returncode=0, stdout="Done.\n")

            state = {}
            with patch.object(pipeline.subprocess, "run", side_effect=fake_run):
                pipeline.run_phase_fetch(args, "critical_run", state)

            cmd = captured["cmd"]
            self.assertIsInstance(cmd, list)
            self.assertNotIn("shell", captured["kwargs"])
            self.assertEqual(cmd[cmd.index("--subs") + 1], "CRMSoftware,SalesOps")
            self.assertEqual(cmd[cmd.index("--seen") + 1], str(pipeline.DATA / "critical_run_seen_post_ids.txt"))
            self.assertEqual(cmd[cmd.index("--keywords") + 1], "crm tools,sales automation")
            self.assertIn("--only_pain_points", cmd)
            self.assertEqual(state["fetch"], "done")

    def test_normalize_does_not_pass_invalid_pain_point_flag(self):
        with tempfile.TemporaryDirectory() as td:
            self.with_pipeline_paths(td)
            pipeline.DATA.mkdir(parents=True)
            (pipeline.DATA / "critical_run_raw.jsonl").write_text("{}\n", encoding="utf-8")
            args = SimpleNamespace()
            captured = {}

            def fake_run(cmd, label, **kwargs):
                captured["cmd"] = cmd
                return SimpleNamespace(returncode=0)

            with patch.object(pipeline, "run", side_effect=fake_run):
                pipeline.run_phase_normalize(args, "critical_run", {})

            self.assertNotIn("--only_pain_points", captured["cmd"])
            self.assertEqual(captured["cmd"][captured["cmd"].index("--output") + 1],
                             str(pipeline.DATA / "critical_run_normalized.jsonl"))

    def test_fetch_failure_marks_phase_failed_and_stops(self):
        with tempfile.TemporaryDirectory() as td:
            self.with_pipeline_paths(td)
            args = SimpleNamespace(
                niche_type="saas",
                subs="CRM",
                max_posts=1,
                prefix=None,
                keywords="crm",
                only_pain_points=False,
            )
            state = {}

            with patch.object(
                pipeline.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=2, stdout="boom"),
            ), self.assertRaises(SystemExit) as raised:
                pipeline.run_phase_fetch(args, "critical_run", state)

            self.assertEqual(raised.exception.code, 2)
            self.assertEqual(state["fetch"], "failed")


class CriticalInputSafetyTests(unittest.TestCase):
    def test_seed_factory_preserves_existing_file_when_generation_fails(self):
        with tempfile.TemporaryDirectory() as td:
            seed_path = Path(td) / "seed_topics.txt"
            seed_path.write_text("curated seed\n", encoding="utf-8")

            with patch.object(seed_factory, "OUTPUT_FILE", str(seed_path)), \
                    patch.object(seed_factory.requests, "post", side_effect=RuntimeError("offline")), \
                    patch.object(sys, "argv", ["seed_factory.py", "--source", "llm", "--topic", "crm"]):
                code = seed_factory.main()

            self.assertEqual(code, 1)
            self.assertEqual(seed_path.read_text(encoding="utf-8"), "curated seed\n")

    def test_rss_miner_missing_seed_file_exits_before_empty_search(self):
        with tempfile.TemporaryDirectory() as td:
            missing_seed_file = str(Path(td) / "missing_seed_topics.txt")

            with patch.object(rss_miner, "SEED_TOPICS_FILE", missing_seed_file), \
                    patch.object(sys, "argv", [
                        "rss_miner.py",
                        "--mode", "urls",
                        "--subs", "CRM",
                        "--include_search",
                    ]), \
                    patch("sys.stdout", new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as raised:
                    rss_miner.main()

            self.assertEqual(raised.exception.code, 1)

    def test_rss_miner_cli_keywords_bypass_seed_file(self):
        with tempfile.TemporaryDirectory() as td:
            missing_seed_file = str(Path(td) / "missing_seed_topics.txt")

            with patch.object(rss_miner, "SEED_TOPICS_FILE", missing_seed_file), \
                    patch.object(sys, "argv", [
                        "rss_miner.py",
                        "--mode", "urls",
                        "--subs", "CRM",
                        "--include_search",
                        "--keywords", "crm tools,sales automation",
                    ]), \
                    patch("sys.stdout", new_callable=io.StringIO) as stdout:
                rss_miner.main()

            output = stdout.getvalue()
            self.assertIn("Total URLs:", output)
            self.assertIn("crm+tools", output)
            self.assertIn("sales+automation", output)


if __name__ == "__main__":
    unittest.main()
