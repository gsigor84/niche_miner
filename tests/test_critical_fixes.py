import contextlib
import io
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


def _install_optional_dependency_stubs():
    if "feedparser" not in sys.modules:
        feedparser = types.ModuleType("feedparser")
        feedparser.FeedParserDict = dict
        feedparser.parse = lambda raw: SimpleNamespace(entries=[])
        sys.modules["feedparser"] = feedparser

    if "bs4" not in sys.modules:
        bs4 = types.ModuleType("bs4")

        class BeautifulSoup:
            def __init__(self, html, parser):
                self.html = html or ""

            def get_text(self, separator=" ", strip=False):
                return self.html.strip() if strip else self.html

        bs4.BeautifulSoup = BeautifulSoup
        sys.modules["bs4"] = bs4

    if "requests" not in sys.modules:
        requests = types.ModuleType("requests")

        class Session:
            headers = {}

            def get(self, *args, **kwargs):
                raise RuntimeError("network disabled in tests")

        requests.Session = Session
        sys.modules["requests"] = requests

    if "networkx" not in sys.modules:
        networkx = types.ModuleType("networkx")
        sys.modules["networkx"] = networkx

    if "numpy" not in sys.modules:
        sys.modules["numpy"] = types.ModuleType("numpy")


_install_optional_dependency_stubs()

import gap_analysis
import pipeline
import rss_miner
import seed_factory


@contextlib.contextmanager
def chdir(path):
    old = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old)


class CriticalFixTests(unittest.TestCase):
    def test_pipeline_decides_phases_after_state_updates(self):
        calls = []

        def mark_done(name):
            def phase(args, run_id, state):
                calls.append(name)
                state[name] = "done"
                pipeline.save_run_state(run_id, state)
            return phase

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            argv = [
                "pipeline.py",
                "--run_id", "dynamic_phases",
                "--keywords", "crm tools",
                "--subs", "CRM",
                "--skip_gap",
            ]
            with mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                 mock.patch.object(pipeline, "DATA", tmp_path / "data"), \
                 mock.patch.object(pipeline, "run_phase_scout", mark_done("scout")), \
                 mock.patch.object(pipeline, "run_phase_fetch", mark_done("fetch")), \
                 mock.patch.object(pipeline, "run_phase_normalize", mark_done("normalize")), \
                 mock.patch.object(sys, "argv", argv):
                pipeline.main()

        self.assertEqual(calls, ["scout", "fetch", "normalize"])

    def test_normalize_phase_no_longer_reads_fetch_only_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            (data_dir / "safe_norm_raw.jsonl").write_text("{}\n", encoding="utf-8")
            state = {}
            calls = []

            def fake_run(cmd, label, check=True):
                calls.append(cmd)

            with mock.patch.object(pipeline, "DATA", data_dir), \
                 mock.patch.object(pipeline, "RUNS", Path(tmp) / "runs"), \
                 mock.patch.object(pipeline, "run", fake_run):
                pipeline.run_phase_normalize(SimpleNamespace(run_id="safe_norm"), "safe_norm", state)

        self.assertEqual(state["normalize"], "done")
        self.assertNotIn("--only_pain_points", calls[0])

    def test_fetch_phase_uses_safe_argv_and_run_scoped_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            data_dir.mkdir()
            captured = []

            def fake_run(cmd, label, check=True):
                captured.append(cmd)
                (data_dir / "fetch_safe_raw.jsonl").write_text('{"post_id":"abc123"}\n', encoding="utf-8")

            args = SimpleNamespace(
                run_id="fetch_safe",
                subs=None,
                niche_type="saas",
                max_posts=10,
                prefix="best",
                keywords="crm tools,sales automation",
                max_keywords=1,
                only_pain_points=True,
            )

            with mock.patch.object(pipeline, "DATA", data_dir), \
                 mock.patch.object(pipeline, "run", fake_run):
                pipeline.run_phase_fetch(args, "fetch_safe", {"subs": "CRM"})

        cmd = captured[0]
        self.assertIsInstance(cmd, list)
        self.assertIn("--keywords", cmd)
        self.assertIn("crm tools,sales automation", cmd)
        self.assertIn("--seen", cmd)
        self.assertIn(str(data_dir / "fetch_safe_seen_post_ids.txt"), cmd)
        self.assertIn("--only_pain_points", cmd)

    def test_seed_factory_preserves_existing_file_when_llm_adds_no_seeds(self):
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp):
            seed_path = Path("seed_topics.txt")
            seed_path.write_text("existing seed\n", encoding="utf-8")

            with mock.patch.object(sys, "argv", [
                "seed_factory.py",
                "--source", "llm",
                "--topic", "broken model",
                "--append",
            ]), mock.patch.object(seed_factory.requests, "post", side_effect=RuntimeError("down"), create=True):
                exit_code = seed_factory.main()

            self.assertEqual(exit_code, 1)
            self.assertEqual(seed_path.read_text(encoding="utf-8"), "existing seed\n")

    def test_rss_miner_uses_explicit_keywords_without_seed_file(self):
        with tempfile.TemporaryDirectory() as tmp, chdir(tmp):
            argv = [
                "rss_miner.py",
                "--mode", "urls",
                "--subs", "CRM",
                "--include_search",
                "--keywords", "crm tools,sales automation",
                "--max_keywords", "1",
                "--prefix", "best",
            ]
            buf = io.StringIO()

            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(buf):
                rss_miner.main()

        output = buf.getvalue()
        self.assertIn("Total URLs: 2", output)
        self.assertIn("best+crm+tools", output)

    def test_gap_analysis_empty_input_exits_nonzero_without_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "empty.jsonl"
            output_path = Path(tmp) / "gaps.json"
            input_path.write_text("", encoding="utf-8")
            argv = [
                "gap_analysis.py",
                "--input", str(input_path),
                "--output", str(output_path),
            ]

            with mock.patch.object(sys, "argv", argv):
                with self.assertRaises(SystemExit) as raised:
                    gap_analysis.main()

            self.assertEqual(raised.exception.code, 1)
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
