import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def import_with_optional_dependency_stubs(module_name):
    sys.modules.setdefault(
        "feedparser",
        types.SimpleNamespace(FeedParserDict=dict, parse=lambda raw: types.SimpleNamespace(entries=[])),
    )
    sys.modules.setdefault(
        "bs4",
        types.SimpleNamespace(BeautifulSoup=lambda html, parser: types.SimpleNamespace(get_text=lambda *a, **k: html or "")),
    )
    sys.modules.setdefault("networkx", types.SimpleNamespace())
    sys.modules.setdefault("numpy", types.SimpleNamespace())
    return importlib.import_module(module_name)


class PipelineCriticalFixTests(unittest.TestCase):
    def test_default_pipeline_rechecks_state_between_phases(self):
        pipeline = importlib.import_module("pipeline")
        calls = []

        def phase(name):
            def _run(args, run_id, state):
                calls.append(name)
                state[name] = "done"

            return _run

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(sys, "argv", ["pipeline.py", "--run_id", "unit", "--topic", "ticketing", "--skip_gap"]), \
                 patch.object(pipeline, "DATA", Path(tmp) / "data"), \
                 patch.object(pipeline, "RUNS", Path(tmp) / "runs"), \
                 patch.object(pipeline, "run_phase_seed", phase("seed")), \
                 patch.object(pipeline, "run_phase_scout", phase("scout")), \
                 patch.object(pipeline, "run_phase_fetch", phase("fetch")), \
                 patch.object(pipeline, "run_phase_normalize", phase("normalize")), \
                 patch.object(pipeline.time, "sleep"):
                pipeline.main()

        self.assertEqual(calls, ["seed", "scout", "fetch", "normalize"])

    def test_normalize_phase_does_not_reference_missing_only_pain_points_arg(self):
        pipeline = importlib.import_module("pipeline")
        commands = []

        def fake_run(cmd, **kwargs):
            commands.append(cmd)
            return types.SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            runs = Path(tmp) / "runs"
            data.mkdir()
            (data / "unit_raw.jsonl").write_text("{}\n", encoding="utf-8")
            args = types.SimpleNamespace(run_id="unit")

            with patch.object(pipeline, "DATA", data), \
                 patch.object(pipeline, "RUNS", runs), \
                 patch.object(pipeline.subprocess, "run", fake_run):
                pipeline.run_phase_normalize(args, "unit", {})

        self.assertEqual(commands[0][0:2], ["python3", "normalize_reddit_jsonl.py"])
        self.assertNotIn("--only_pain_points", commands[0])

    def test_fetch_phase_uses_keywords_prefix_run_seen_and_scout_subs(self):
        pipeline = importlib.import_module("pipeline")
        commands = []

        def fake_run(cmd, **kwargs):
            commands.append(cmd)
            return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            args = types.SimpleNamespace(
                niche_type="events",
                subs=None,
                max_posts=5,
                run_id="unit",
                prefix="cheap",
                keywords="ticket bots,venue fees",
            )
            state = {"scout_subs": "concerts,eventplanning"}

            with patch.object(pipeline, "DATA", Path(tmp) / "data"), \
                 patch.object(pipeline, "RUNS", Path(tmp) / "runs"), \
                 patch.object(pipeline.subprocess, "run", fake_run):
                pipeline.run_phase_fetch(args, "unit", state)

        cmd = commands[0]
        self.assertIsInstance(cmd, list)
        self.assertEqual(cmd[cmd.index("--subs") + 1], "concerts,eventplanning")
        self.assertEqual(cmd[cmd.index("--prefix") + 1], "cheap")
        self.assertEqual(cmd[cmd.index("--keywords") + 1], "ticket bots,venue fees")
        self.assertIn("unit_seen_post_ids.txt", cmd[cmd.index("--seen") + 1])
        self.assertEqual(state["fetch"], "done")


class SeedFactoryCriticalFixTests(unittest.TestCase):
    def test_failed_llm_generation_does_not_overwrite_existing_seed_file(self):
        seed_factory = importlib.import_module("seed_factory")

        with tempfile.TemporaryDirectory() as tmp:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmp)
                seed_file = Path("seed_topics.txt")
                seed_file.write_text("# Existing\ncurated topic\n", encoding="utf-8")

                with patch.object(sys, "argv", ["seed_factory.py", "--source", "llm", "--topic", "tickets"]), \
                     patch.object(seed_factory.requests, "post", side_effect=RuntimeError("ollama down")):
                    with self.assertRaises(SystemExit) as raised:
                        seed_factory.main()

                self.assertEqual(raised.exception.code, 1)
                self.assertEqual(seed_file.read_text(encoding="utf-8"), "# Existing\ncurated topic\n")
            finally:
                os.chdir(old_cwd)


class RssMinerCriticalFixTests(unittest.TestCase):
    def test_cli_keywords_are_parsed_with_prefix(self):
        rss_miner = import_with_optional_dependency_stubs("rss_miner")

        self.assertEqual(
            rss_miner.parse_keywords("ticket bots, venue fees", prefix="cheap"),
            ["cheap ticket bots", "cheap venue fees"],
        )


class GapAnalysisCriticalFixTests(unittest.TestCase):
    def test_reddit_footer_does_not_become_gap_keyword(self):
        gap_analysis = import_with_optional_dependency_stubs("gap_analysis")

        keywords = gap_analysis.extract_keywords(
            "real logistics real logistics submitted by /u/example [link] [comments] "
            "submitted by /u/example [link] [comments]",
            top_n=20,
        )

        self.assertIn("real_logistics", keywords)
        self.assertNotIn("link_comments", keywords)
        self.assertNotIn("submitted", keywords)


class AnalyzeMarketCriticalFixTests(unittest.TestCase):
    def test_failed_batch_aborts_without_success_report(self):
        analyze_market = importlib.import_module("analyze_market")

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(analyze_market, "OUTPUT_DIR", tmp), \
                 patch.object(analyze_market.requests, "post", side_effect=RuntimeError("ollama down")):
                report_path = analyze_market.generate_report(
                    [{"title": "t", "summary": "s", "comments": []}],
                    model="missing",
                    batch_size=1,
                )

            self.assertIsNone(report_path)
            self.assertEqual(list(Path(tmp).glob("*.md")), [])


if __name__ == "__main__":
    unittest.main()
