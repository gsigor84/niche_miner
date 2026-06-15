import os
import json
import sys
import tempfile
import types
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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
                self.html = html or ""

            def get_text(self, separator=" ", strip=False):
                text = str(self.html)
                return text.strip() if strip else text

        bs4.BeautifulSoup = BeautifulSoup
        sys.modules["bs4"] = bs4

    if "requests" not in sys.modules:
        requests = types.ModuleType("requests")

        class Session:
            def __init__(self):
                self.headers = {}

            def get(self, *args, **kwargs):
                raise RuntimeError("requests stub should not be used in unit tests")

        requests.Session = Session
        sys.modules["requests"] = requests

    if "networkx" not in sys.modules:
        sys.modules["networkx"] = types.ModuleType("networkx")

    if "numpy" not in sys.modules:
        sys.modules["numpy"] = types.ModuleType("numpy")


install_optional_dependency_stubs()

import gap_analysis
import pipeline
import rss_miner
import seed_factory


class WorkingDirectory:
    def __init__(self, path):
        self.path = path
        self.previous = None

    def __enter__(self):
        self.previous = os.getcwd()
        os.chdir(self.path)

    def __exit__(self, exc_type, exc, tb):
        os.chdir(self.previous)


def pipeline_args(**overrides):
    defaults = {
        "run_id": "critical_run",
        "topic": "crm tools",
        "keywords": None,
        "niche_type": "saas",
        "prefix": None,
        "subs": None,
        "resume": False,
        "phase": None,
        "seed_count": 2,
        "max_seeds": 2,
        "max_posts": 1,
        "only_pain_points": False,
        "top_gaps": 5,
        "min_degree": 1,
        "viz": False,
        "input": None,
        "skip_seed": False,
        "skip_gap": False,
        "skip_scout": False,
    }
    defaults.update(overrides)
    return Namespace(**defaults)


class PipelineCriticalFixTests(unittest.TestCase):
    def test_fresh_pipeline_runs_all_remaining_phases_in_one_invocation(self):
        executed = []

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            def phase(name):
                def run_phase(args, run_id, state):
                    executed.append(name)
                    state[name] = "done"
                    pipeline.save_run_state(run_id, state)

                return run_phase

            args = pipeline_args()
            with (
                patch.object(pipeline, "DATA", tmp_path / "data"),
                patch.object(pipeline, "RUNS", tmp_path / "runs"),
                patch.object(pipeline, "SEED_FILE", tmp_path / "seed_topics.txt"),
                patch.object(pipeline, "parse_args", return_value=args),
                patch.object(pipeline, "run_phase_seed", phase("seed")),
                patch.object(pipeline, "run_phase_scout", phase("scout")),
                patch.object(pipeline, "run_phase_fetch", phase("fetch")),
                patch.object(pipeline, "run_phase_normalize", phase("normalize")),
                patch.object(pipeline, "run_phase_gap", phase("gap")),
                patch.object(pipeline.time, "sleep", lambda _: None),
            ):
                pipeline.main()

            self.assertEqual(["seed", "scout", "fetch", "normalize", "gap"], executed)
            state = json.loads((tmp_path / "runs" / args.run_id / "state.json").read_text(encoding="utf-8"))
            self.assertEqual("done", state["gap"])

    def test_normalize_phase_does_not_reference_fetch_only_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_dir = tmp_path / "data"
            runs_dir = tmp_path / "runs"
            data_dir.mkdir()
            (data_dir / "critical_run_raw.jsonl").write_text("{}\n", encoding="utf-8")
            calls = []

            def fake_run(cmd, label, check=True):
                calls.append(cmd)
                return types.SimpleNamespace(returncode=0)

            args = Namespace(run_id="critical_run", input=None)
            state = {}
            with (
                patch.object(pipeline, "DATA", data_dir),
                patch.object(pipeline, "RUNS", runs_dir),
                patch.object(pipeline, "run", fake_run),
            ):
                pipeline.run_phase_normalize(args, args.run_id, state)

            self.assertEqual("done", state["normalize"])
            self.assertNotIn("--only_pain_points", calls[0])

    def test_fetch_phase_uses_argv_keywords_discovered_subs_and_run_seen_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_dir = tmp_path / "data"
            data_dir.mkdir()
            raw_path = data_dir / "critical_run_raw.jsonl"
            calls = []

            def fake_subprocess_run(cmd, **kwargs):
                calls.append((cmd, kwargs))
                raw_path.write_text("{}\n", encoding="utf-8")
                return types.SimpleNamespace(returncode=0, stdout="ok", stderr="")

            args = pipeline_args(
                keywords="crm tools,sales automation",
                prefix="best",
                topic=None,
            )
            state = {"scout_subs": ["CRMSoftware", "CRM"]}
            with (
                patch.object(pipeline, "DATA", data_dir),
                patch.object(pipeline, "RUNS", tmp_path / "runs"),
                patch.object(pipeline.subprocess, "run", fake_subprocess_run),
            ):
                pipeline.run_phase_fetch(args, args.run_id, state)

            cmd, kwargs = calls[0]
            self.assertIsInstance(cmd, list)
            self.assertNotIn("shell", kwargs)
            self.assertEqual("CRMSoftware,CRM", cmd[cmd.index("--subs") + 1])
            self.assertEqual("crm tools,sales automation", cmd[cmd.index("--keywords") + 1])
            self.assertEqual("data/critical_run_seen_post_ids.txt", cmd[cmd.index("--seen") + 1])
            self.assertEqual("done", state["fetch"])

    def test_scout_failure_does_not_mark_phase_done(self):
        args = pipeline_args(keywords="crm tools", topic=None)
        state = {}
        result = types.SimpleNamespace(returncode=2, stdout="", stderr="bad args")

        with patch.object(pipeline.subprocess, "run", return_value=result):
            with self.assertRaises(SystemExit) as cm:
                pipeline.run_phase_scout(args, args.run_id, state)

        self.assertEqual(2, cm.exception.code)
        self.assertNotIn("scout", state)


class ProducerFailureTests(unittest.TestCase):
    def test_seed_factory_preserves_existing_file_when_llm_adds_no_seeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_file = Path(tmp) / "seed_topics.txt"
            original = "# existing\ncrm tools\n"
            seed_file.write_text(original, encoding="utf-8")

            with (
                WorkingDirectory(tmp),
                patch.object(sys, "argv", ["seed_factory.py", "--source", "llm", "--topic", "crm"]),
                patch.object(seed_factory.SeedFactory, "brainstorm_llm", lambda self, *args, **kwargs: None),
            ):
                with self.assertRaises(SystemExit) as cm:
                    seed_factory.main()

            self.assertEqual(1, cm.exception.code)
            self.assertEqual(original, seed_file.read_text(encoding="utf-8"))

    def test_rss_miner_fails_search_mode_without_keywords(self):
        with tempfile.TemporaryDirectory() as tmp:
            with (
                WorkingDirectory(tmp),
                patch.object(sys, "argv", ["rss_miner.py", "--mode", "urls"]),
            ):
                with self.assertRaises(SystemExit) as cm:
                    rss_miner.main()

        self.assertEqual(1, cm.exception.code)

    def test_gap_analysis_fails_empty_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty_input = Path(tmp) / "empty.jsonl"
            empty_input.write_text("", encoding="utf-8")
            with patch.object(sys, "argv", ["gap_analysis.py", "--input", str(empty_input)]):
                with self.assertRaises(SystemExit) as cm:
                    gap_analysis.main()

        self.assertEqual(1, cm.exception.code)


if __name__ == "__main__":
    unittest.main()
