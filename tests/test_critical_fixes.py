import contextlib
import io
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


if "feedparser" not in sys.modules:
    feedparser_stub = types.ModuleType("feedparser")
    feedparser_stub.FeedParserDict = dict
    feedparser_stub.parse = lambda raw: SimpleNamespace(entries=[])
    sys.modules["feedparser"] = feedparser_stub

if "bs4" not in sys.modules:
    bs4_stub = types.ModuleType("bs4")

    class DummySoup:
        def __init__(self, html, parser):
            self.html = html

        def get_text(self, separator=" ", strip=False):
            text = self.html or ""
            return text.strip() if strip else text

    bs4_stub.BeautifulSoup = DummySoup
    sys.modules["bs4"] = bs4_stub


import pipeline
import rss_miner
import seed_factory


class PipelineCriticalFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.runs = self.root / "runs"
        self.data.mkdir()
        self.runs.mkdir()
        self.seed_file = self.root / "seed_topics.txt"

        self.patches = [
            mock.patch.object(pipeline, "DATA", self.data),
            mock.patch.object(pipeline, "RUNS", self.runs),
            mock.patch.object(pipeline, "SEED_FILE", self.seed_file),
            mock.patch.object(pipeline.time, "sleep", lambda _: None),
        ]
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()
        self.tmp.cleanup()

    def test_fresh_full_run_continues_after_each_phase_updates_state(self):
        calls = []

        def phase(name):
            def run_phase(args, run_id, state):
                calls.append(name)
                state[name] = "done"
                pipeline.save_run_state(run_id, state)

            return run_phase

        with mock.patch.object(pipeline, "run_phase_seed", phase("seed")), \
             mock.patch.object(pipeline, "run_phase_scout", phase("scout")), \
             mock.patch.object(pipeline, "run_phase_fetch", phase("fetch")), \
             mock.patch.object(pipeline, "run_phase_normalize", phase("normalize")), \
             mock.patch.object(sys, "argv", [
                 "pipeline.py",
                 "--topic", "crm software",
                 "--run_id", "fresh_run",
                 "--skip_gap",
             ]):
            pipeline.main()

        self.assertEqual(calls, ["seed", "scout", "fetch", "normalize"])

    def test_normalize_phase_does_not_reference_fetch_only_flag(self):
        raw = self.data / "demo_raw.jsonl"
        raw.write_text("{}\n", encoding="utf-8")
        captured = []

        with mock.patch.object(pipeline, "run", side_effect=lambda cmd, label, check=True: captured.append(cmd)):
            args = SimpleNamespace(run_id="demo")
            pipeline.run_phase_normalize(args, "demo", {})

        self.assertEqual(captured[0][:3], ["python3", "normalize_reddit_jsonl.py", "--input"])
        self.assertNotIn("--only_pain_points", captured[0])

    def test_seed_phase_appends_to_preserve_existing_seed_file(self):
        captured = []
        args = SimpleNamespace(
            keywords=None,
            topic="crm software",
            seed_count=5,
        )

        with mock.patch.object(pipeline, "run", side_effect=lambda cmd, label, check=True: captured.append(cmd)):
            pipeline.run_phase_seed(args, "demo", {})

        self.assertIn("--append", captured[0])

    def test_scout_failure_is_not_marked_done(self):
        state = {}
        args = SimpleNamespace(
            keywords="crm software,sales automation",
            max_seeds=5,
            subs=None,
        )
        failed = SimpleNamespace(returncode=2, stdout="", stderr="bad args")

        with mock.patch.object(pipeline.subprocess, "run", return_value=failed):
            with self.assertRaises(SystemExit) as raised:
                pipeline.run_phase_scout(args, "demo", state)

        self.assertEqual(raised.exception.code, 2)
        self.assertNotEqual(state.get("scout"), "done")

    def test_fetch_forwards_cli_keywords_and_uses_run_scoped_seen_file(self):
        captured = []
        args = SimpleNamespace(
            run_id="demo",
            niche_type="saas",
            subs=None,
            max_posts=7,
            prefix="best",
            keywords="crm software,sales automation",
            only_pain_points=True,
        )
        state = {"subs": "SaaS,CRM"}

        with mock.patch.object(pipeline, "run", side_effect=lambda cmd, label, check=True: captured.append(cmd)):
            pipeline.run_phase_fetch(args, "demo", state)

        cmd = captured[0]
        self.assertEqual(cmd[cmd.index("--subs") + 1], "SaaS,CRM")
        self.assertEqual(cmd[cmd.index("--keywords") + 1], "crm software,sales automation")
        self.assertEqual(cmd[cmd.index("--seen") + 1], "data/demo_seen_post_ids.txt")
        self.assertIn("--only_pain_points", cmd)
        self.assertEqual(state["fetch"], "done")

    def test_gap_phase_requires_success_before_state_is_marked_done(self):
        normalized = self.data / "demo_normalized.jsonl"
        normalized.write_text("{}\n", encoding="utf-8")
        checks = []
        args = SimpleNamespace(
            run_id="demo",
            input=None,
            top_gaps=20,
            min_degree=2,
            viz=False,
        )

        with mock.patch.object(pipeline, "run", side_effect=lambda cmd, label, check=True: checks.append(check)):
            pipeline.run_phase_gap(args, "demo", {})

        self.assertEqual(checks, [True])


class RssMinerCriticalFixTests(unittest.TestCase):
    def test_cli_keywords_are_used_for_search_urls(self):
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", [
            "rss_miner.py",
            "--mode", "urls",
            "--niche_type", "saas",
            "--subs", "SaaS",
            "--keywords", "crm software,sales automation",
            "--include_search",
        ]), contextlib.redirect_stdout(stdout):
            rss_miner.main()

        output = stdout.getvalue()
        self.assertIn("q=crm+software", output)
        self.assertIn("q=sales+automation", output)

    def test_search_mode_without_keywords_fails_instead_of_succeeding_with_zero_feeds(self):
        with mock.patch.object(rss_miner, "load_keywords", return_value=[]), \
             mock.patch.object(sys, "argv", [
                 "rss_miner.py",
                 "--mode", "urls",
                 "--subs", "SaaS",
                 "--include_search",
             ]):
            with self.assertRaises(SystemExit) as raised:
                rss_miner.main()

        self.assertEqual(raised.exception.code, 1)

    def test_default_seen_file_is_sidecar_to_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            captured = []
            args = SimpleNamespace(
                out=str(Path(tmp) / "demo_raw.jsonl"),
                seen=None,
                subs=[],
                keywords=[],
                templates=[],
                t="month",
                sort="top",
                include_top=False,
                include_new=False,
                include_search=False,
                prefix=None,
                max_posts=1,
                include_comments=False,
                max_comments=0,
                sleep=0,
                only_pain_points=False,
            )

            with mock.patch.object(rss_miner, "load_seen_ids", side_effect=lambda path: captured.append(path) or set()):
                rss_miner.run_fetch(args)

        self.assertEqual(captured[0].name, "demo_raw_seen_post_ids.txt")


class SeedFactoryCriticalFixTests(unittest.TestCase):
    def test_generation_failure_preserves_existing_seed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_file = Path(tmp) / "seed_topics.txt"
            seed_file.write_text("existing seed\n", encoding="utf-8")
            seed_factory_class = seed_factory.SeedFactory

            with mock.patch.object(seed_factory, "SeedFactory", lambda: seed_factory_class(str(seed_file))), \
                 mock.patch.object(seed_factory.requests, "post", side_effect=RuntimeError("llm down"), create=True), \
                 mock.patch.object(sys, "argv", [
                     "seed_factory.py",
                     "--source", "llm",
                     "--topic", "crm",
                     "--count", "3",
                 ]):
                code = seed_factory.main()

            self.assertEqual(code, 1)
            self.assertEqual(seed_file.read_text(encoding="utf-8"), "existing seed\n")

    def test_append_mode_still_fails_when_generation_adds_no_new_seeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_file = Path(tmp) / "seed_topics.txt"
            seed_file.write_text("existing seed\n", encoding="utf-8")
            seed_factory_class = seed_factory.SeedFactory

            with mock.patch.object(seed_factory, "SeedFactory", lambda: seed_factory_class(str(seed_file))), \
                 mock.patch.object(seed_factory.requests, "post", side_effect=RuntimeError("llm down"), create=True), \
                 mock.patch.object(sys, "argv", [
                     "seed_factory.py",
                     "--source", "llm",
                     "--topic", "crm",
                     "--append",
                 ]):
                code = seed_factory.main()

            self.assertEqual(code, 1)
            self.assertEqual(seed_file.read_text(encoding="utf-8"), "existing seed\n")


if __name__ == "__main__":
    unittest.main()
