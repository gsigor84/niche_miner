import contextlib
import importlib
import io
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


def install_optional_dependency_stubs():
    if "feedparser" not in sys.modules:
        feedparser = types.ModuleType("feedparser")
        feedparser.FeedParserDict = dict
        feedparser.parse = lambda raw: types.SimpleNamespace(entries=[])
        sys.modules["feedparser"] = feedparser

    if "bs4" not in sys.modules:
        bs4 = types.ModuleType("bs4")

        class BeautifulSoup:
            def __init__(self, html, parser):
                self.html = html

            def get_text(self, separator=" ", strip=False):
                text = str(self.html)
                return text.strip() if strip else text

        bs4.BeautifulSoup = BeautifulSoup
        sys.modules["bs4"] = bs4

    if "networkx" not in sys.modules:
        sys.modules["networkx"] = types.ModuleType("networkx")

    if "numpy" not in sys.modules:
        sys.modules["numpy"] = types.ModuleType("numpy")


install_optional_dependency_stubs()

import gap_analysis
import pipeline
import rss_miner
import scout_subreddits
import seed_factory


@contextlib.contextmanager
def chdir(path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


class PipelineCriticalFixTests(unittest.TestCase):
    def test_full_run_executes_later_phases_after_state_updates(self):
        calls = []

        def fake_phase(name):
            def _phase(args, run_id, state):
                calls.append(name)
                state[name] = "done"
                pipeline.save_run_state(run_id, state)

            return _phase

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(pipeline, "PROJECT", tmp_path), \
                    mock.patch.object(pipeline, "DATA", tmp_path / "data"), \
                    mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                    mock.patch.object(pipeline, "SEED_FILE", tmp_path / "seed_topics.txt"), \
                    mock.patch.object(pipeline, "run_phase_seed", fake_phase("seed")), \
                    mock.patch.object(pipeline, "run_phase_scout", fake_phase("scout")), \
                    mock.patch.object(pipeline, "run_phase_fetch", fake_phase("fetch")), \
                    mock.patch.object(pipeline, "run_phase_normalize", fake_phase("normalize")), \
                    mock.patch.object(pipeline, "run_phase_gap", fake_phase("gap")), \
                    mock.patch.object(pipeline.time, "sleep", lambda _: None), \
                    mock.patch.object(sys, "argv", ["pipeline.py", "--run_id", "run1", "--keywords", "crm tools"]):
                pipeline.main()

        self.assertEqual(calls, ["scout", "fetch", "normalize", "gap"])

    def test_fetch_uses_argv_keywords_run_scoped_seen_and_scouted_subs(self):
        captured = {}

        def fake_run(cmd, label, check=True, capture_output=False):
            captured["cmd"] = cmd
            out_path = Path(cmd[cmd.index("--out") + 1])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text('{"post_id":"abc123"}\n', encoding="utf-8")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        args = types.SimpleNamespace(
            niche_type="saas",
            subs=None,
            max_posts=5,
            prefix="best",
            keywords="crm tools,sales automation",
            max_seeds=2,
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state = {"scout_subs": ["CRM", "sales"]}
            with mock.patch.object(pipeline, "DATA", tmp_path / "data"), \
                    mock.patch.object(pipeline, "PROJECT", tmp_path), \
                    mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                    mock.patch.object(pipeline, "run", fake_run):
                pipeline.run_phase_fetch(args, "rid", state)

        cmd = captured["cmd"]
        self.assertIsInstance(cmd, list)
        self.assertEqual(cmd[cmd.index("--subs") + 1], "CRM,sales")
        self.assertEqual(cmd[cmd.index("--keywords") + 1], "crm tools,sales automation")
        self.assertEqual(cmd[cmd.index("--prefix") + 1], "best")
        self.assertTrue(cmd[cmd.index("--seen") + 1].endswith("rid_seen_post_ids.txt"))
        self.assertEqual(state["fetch"], "done")

    def test_fetch_failure_does_not_mark_state_done(self):
        def fake_run(cmd, label, check=True, capture_output=False):
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        args = types.SimpleNamespace(
            niche_type="saas",
            subs="CRM",
            max_posts=5,
            prefix=None,
            keywords=None,
            max_seeds=2,
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            state = {}
            with mock.patch.object(pipeline, "DATA", tmp_path / "data"), \
                    mock.patch.object(pipeline, "PROJECT", tmp_path), \
                    mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                    mock.patch.object(pipeline, "run", fake_run), \
                    self.assertRaises(SystemExit):
                pipeline.run_phase_fetch(args, "rid", state)

        self.assertNotIn("fetch", state)


class SeedFactoryCriticalFixTests(unittest.TestCase):
    def test_failed_google_harvest_preserves_existing_seed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_path = Path(tmp) / "seed_topics.txt"
            seed_path.write_text("existing seed\n", encoding="utf-8")

            with chdir(tmp), \
                    mock.patch.object(sys, "argv", ["seed_factory.py", "--source", "google"]), \
                    mock.patch.object(seed_factory.requests, "get", side_effect=RuntimeError("offline")), \
                    self.assertRaises(SystemExit) as raised:
                seed_factory.main()

            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(seed_path.read_text(encoding="utf-8"), "existing seed\n")


class RssMinerCriticalFixTests(unittest.TestCase):
    def test_urls_mode_accepts_explicit_keywords_and_caps_them(self):
        stdout = io.StringIO()
        argv = [
            "rss_miner.py",
            "--mode", "urls",
            "--niche_type", "saas",
            "--subs", "CRM",
            "--include_search",
            "--keywords", "crm tools,sales automation",
            "--max_keywords", "1",
        ]

        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(stdout):
            rss_miner.main()

        output = stdout.getvalue()
        self.assertIn("crm+tools", output)
        self.assertNotIn("sales+automation", output)

    def test_search_without_keywords_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            with chdir(tmp), \
                    mock.patch.object(sys, "argv", ["rss_miner.py", "--mode", "urls", "--subs", "CRM", "--include_search"]), \
                    self.assertRaises(SystemExit) as raised:
                rss_miner.main()

        self.assertEqual(raised.exception.code, 1)


class ScoutSubredditsCriticalFixTests(unittest.TestCase):
    def test_no_discovered_subreddits_exits_nonzero(self):
        with mock.patch.object(sys, "argv", ["scout_subreddits.py", "unlikely niche"]), \
                mock.patch.object(scout_subreddits, "search_subreddits", return_value=[]), \
                self.assertRaises(SystemExit) as raised:
            scout_subreddits.main()

        self.assertEqual(raised.exception.code, 2)


class GapAnalysisCriticalFixTests(unittest.TestCase):
    def test_empty_input_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "empty.jsonl"
            input_path.write_text("", encoding="utf-8")
            with mock.patch.object(sys, "argv", ["gap_analysis.py", "--input", str(input_path)]), \
                    self.assertRaises(SystemExit) as raised:
                gap_analysis.main()

        self.assertEqual(raised.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
