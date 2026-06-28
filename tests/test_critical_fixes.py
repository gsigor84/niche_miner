import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _install_optional_dependency_stubs():
    try:
        import feedparser  # noqa: F401
    except ImportError:
        sys.modules["feedparser"] = types.SimpleNamespace(
            parse=lambda _text: types.SimpleNamespace(entries=[]),
            FeedParserDict=dict,
        )

    try:
        import bs4  # noqa: F401
    except ImportError:
        class BeautifulSoup:
            def __init__(self, html, _parser):
                self.html = html or ""

            def get_text(self, _separator, strip=False):
                return self.html.strip() if strip else self.html

        sys.modules["bs4"] = types.SimpleNamespace(BeautifulSoup=BeautifulSoup)

    try:
        import requests  # noqa: F401
    except ImportError:
        class Session:
            def __init__(self):
                self.headers = {}

            def get(self, *_args, **_kwargs):
                raise RuntimeError("requests stub has no network")

        sys.modules["requests"] = types.SimpleNamespace(
            Session=Session,
            get=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("requests stub has no network")),
            post=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("requests stub has no network")),
        )

    try:
        import networkx  # noqa: F401
    except ImportError:
        sys.modules["networkx"] = types.SimpleNamespace()

    try:
        import numpy  # noqa: F401
    except ImportError:
        sys.modules["numpy"] = types.SimpleNamespace()


_install_optional_dependency_stubs()

import gap_analysis
import pipeline
import rss_miner
import seed_factory


@contextlib.contextmanager
def chdir(path):
    old_cwd = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_cwd)


class CriticalFixTests(unittest.TestCase):
    def test_fresh_keyword_pipeline_runs_downstream_phases(self):
        calls = []

        with tempfile.TemporaryDirectory() as td:
            temp_root = Path(td)

            def make_phase(name):
                def phase(_args, run_id, state):
                    calls.append(name)
                    state[name] = "done"
                    pipeline.save_run_state(run_id, state)

                return phase

            with (
                mock.patch.object(pipeline, "DATA", temp_root / "data"),
                mock.patch.object(pipeline, "RUNS", temp_root / "runs"),
                mock.patch.object(pipeline, "run_phase_scout", make_phase("scout")),
                mock.patch.object(pipeline, "run_phase_fetch", make_phase("fetch")),
                mock.patch.object(pipeline, "run_phase_normalize", make_phase("normalize")),
                mock.patch.object(pipeline, "run_phase_gap", make_phase("gap")),
                mock.patch.object(pipeline.time, "sleep", lambda _seconds: None),
                mock.patch.object(sys, "argv", [
                    "pipeline.py",
                    "--run_id", "critical_run",
                    "--keywords", "crm tools",
                ]),
            ):
                pipeline.main()

            self.assertEqual(calls, ["scout", "fetch", "normalize", "gap"])
            state = json.loads((temp_root / "runs" / "critical_run" / "state.json").read_text())
            self.assertEqual(state["gap"], "done")

    def test_scout_phase_uses_argv_and_persists_discovered_subs(self):
        captured = []

        class Result:
            returncode = 0
            stdout = "noise\nTo use with rss_miner: --subs CRMSoftware,CRM\n"

        def fake_run(cmd, **_kwargs):
            captured.append(cmd)
            return Result()

        with tempfile.TemporaryDirectory() as td:
            with (
                mock.patch.object(pipeline, "RUNS", Path(td) / "runs"),
                mock.patch.object(pipeline.subprocess, "run", fake_run),
            ):
                args = types.SimpleNamespace(
                    keywords="crm tools,sales automation",
                    max_seeds=5,
                )
                state = {}
                pipeline.run_phase_scout(args, "handoff_run", state)

            self.assertIsInstance(captured[0], list)
            self.assertEqual(captured[0][2], "crm tools,sales automation")
            self.assertEqual(state["subs"], "CRMSoftware,CRM")
            saved = json.loads((Path(td) / "runs" / "handoff_run" / "state.json").read_text())
            self.assertEqual(saved["subs"], "CRMSoftware,CRM")

    def test_seed_factory_preserves_existing_file_when_llm_adds_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            seed_file = Path(td) / "seed_topics.txt"
            original = "# existing\ncrm automation\n"
            seed_file.write_text(original)

            with (
                chdir(td),
                mock.patch.object(sys, "argv", [
                    "seed_factory.py",
                    "--source", "llm",
                    "--topic", "crm",
                ]),
                mock.patch.object(seed_factory.requests, "post", side_effect=RuntimeError("ollama unavailable")),
            ):
                with self.assertRaises(SystemExit) as raised:
                    seed_factory.main()

            self.assertNotEqual(raised.exception.code, 0)
            self.assertEqual(seed_file.read_text(), original)

    def test_rss_miner_uses_cli_keywords_without_seed_file(self):
        with tempfile.TemporaryDirectory() as td:
            stdout = io.StringIO()
            with (
                chdir(td),
                mock.patch.object(sys, "argv", [
                    "rss_miner.py",
                    "--mode", "urls",
                    "--subs", "CRM",
                    "--keywords", "crm tools",
                    "--max_keywords", "1",
                ]),
                contextlib.redirect_stdout(stdout),
            ):
                rss_miner.main()

            output = stdout.getvalue()
            self.assertIn("Total URLs: 2", output)
            self.assertIn("crm+tools+best", output)

    def test_gap_analysis_empty_input_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as td:
            empty_input = Path(td) / "empty.jsonl"
            empty_input.write_text("")

            with (
                mock.patch.object(sys, "argv", [
                    "gap_analysis.py",
                    "--input", str(empty_input),
                    "--output", str(Path(td) / "gaps.json"),
                ]),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                with self.assertRaises(SystemExit) as raised:
                    gap_analysis.main()

            self.assertNotEqual(raised.exception.code, 0)
            self.assertFalse((Path(td) / "gaps.json").exists())


if __name__ == "__main__":
    unittest.main()
