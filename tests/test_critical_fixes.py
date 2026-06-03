import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

if importlib.util.find_spec("feedparser") is None:
    sys.modules["feedparser"] = types.SimpleNamespace(
        FeedParserDict=dict,
        parse=lambda raw: types.SimpleNamespace(entries=[]),
    )

if importlib.util.find_spec("bs4") is None:
    class _BeautifulSoup:
        def __init__(self, html, parser):
            self.html = html

        def get_text(self, separator=" ", strip=True):
            return self.html.strip() if strip else self.html

    sys.modules["bs4"] = types.SimpleNamespace(BeautifulSoup=_BeautifulSoup)

if importlib.util.find_spec("requests") is None:
    class _Session:
        def __init__(self):
            self.headers = {}

    sys.modules["requests"] = types.SimpleNamespace(Session=_Session)

if importlib.util.find_spec("networkx") is None:
    sys.modules["networkx"] = types.SimpleNamespace()

if importlib.util.find_spec("numpy") is None:
    sys.modules["numpy"] = types.SimpleNamespace()

import gap_analysis
import pipeline
import rss_miner
import seed_factory


def make_args(**overrides):
    values = {
        "run_id": "critical_run",
        "topic": None,
        "keywords": None,
        "niche_type": "saas",
        "prefix": None,
        "subs": None,
        "seed_count": 10,
        "max_seeds": 20,
        "max_posts": 10,
        "top_gaps": 20,
        "min_degree": 3,
        "viz": False,
        "input": None,
        "skip_seed": False,
        "skip_gap": False,
        "skip_scout": False,
    }
    values.update(overrides)
    return types.SimpleNamespace(**values)


class PipelineCriticalFixTests(unittest.TestCase):
    def test_fresh_full_run_executes_downstream_phases_after_state_updates(self):
        calls = []

        def phase(name):
            def _run(args, run_id, state):
                calls.append(name)
                state[name] = "done"
                pipeline.save_run_state(run_id, state)
            return _run

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            argv = [
                "pipeline.py",
                "--run_id", "critical_run",
                "--topic", "crm",
                "--subs", "CRMSoftware",
            ]

            with mock.patch.object(pipeline, "DATA", tmp_path / "data"), \
                 mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                 mock.patch.object(sys, "argv", argv), \
                 mock.patch.object(pipeline.time, "sleep", lambda _: None), \
                 mock.patch.object(pipeline, "run_phase_seed", phase("seed")), \
                 mock.patch.object(pipeline, "run_phase_scout", phase("scout")), \
                 mock.patch.object(pipeline, "run_phase_fetch", phase("fetch")), \
                 mock.patch.object(pipeline, "run_phase_normalize", phase("normalize")), \
                 mock.patch.object(pipeline, "run_phase_gap", phase("gap")):
                pipeline.main()

        self.assertEqual(calls, ["seed", "scout", "fetch", "normalize", "gap"])

    def test_normalize_phase_has_no_missing_only_pain_points_attribute(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_dir = tmp_path / "data"
            runs_dir = tmp_path / "runs"
            data_dir.mkdir()
            (data_dir / "critical_run_raw.jsonl").write_text("{}\n", encoding="utf-8")

            captured = {}

            def fake_run(cmd, label, check=True):
                captured["cmd"] = cmd
                return types.SimpleNamespace(returncode=0)

            with mock.patch.object(pipeline, "DATA", data_dir), \
                 mock.patch.object(pipeline, "RUNS", runs_dir), \
                 mock.patch.object(pipeline, "run", fake_run):
                state = {}
                pipeline.run_phase_normalize(make_args(), "critical_run", state)

            self.assertEqual(state["normalize"], "done")
            self.assertNotIn("--only_pain_points", captured["cmd"])
            self.assertEqual(
                json.loads((runs_dir / "critical_run" / "state.json").read_text(encoding="utf-8")),
                {"normalize": "done"},
            )

    def test_scout_passes_multi_word_keywords_as_one_arg_and_records_subs(self):
        completed = types.SimpleNamespace(
            returncode=0,
            stdout="To use with rss_miner: --subs CRMSoftware,sales\n",
            stderr="",
        )
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(pipeline, "RUNS", Path(tmp) / "runs"), \
                 mock.patch.object(pipeline.subprocess, "run", return_value=completed) as run_mock:
                state = {}
                pipeline.run_phase_scout(
                    make_args(keywords="crm tools,sales automation"),
                    "critical_run",
                    state,
                )

        run_mock.assert_called_once()
        cmd = run_mock.call_args.args[0]
        self.assertIsInstance(cmd, list)
        self.assertEqual(cmd[2], "crm tools,sales automation")
        self.assertNotIn("shell", run_mock.call_args.kwargs)
        self.assertEqual(state["subreddits"], ["CRMSoftware", "sales"])
        self.assertEqual(state["scout"], "done")

    def test_fetch_uses_discovered_subs_keywords_and_run_scoped_seen_file(self):
        captured = {}

        def fake_run(cmd, label, check=True):
            captured["cmd"] = cmd
            return types.SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(pipeline, "RUNS", Path(tmp) / "runs"), \
                 mock.patch.object(pipeline, "run", fake_run):
                state = {"subreddits": ["CRMSoftware", "sales"]}
                pipeline.run_phase_fetch(
                    make_args(keywords="crm tools", prefix="best"),
                    "critical_run",
                    state,
                )

        cmd = captured["cmd"]
        self.assertEqual(cmd[cmd.index("--subs") + 1], "CRMSoftware,sales")
        self.assertEqual(cmd[cmd.index("--keywords") + 1], "crm tools")
        self.assertEqual(cmd[cmd.index("--prefix") + 1], "best")
        self.assertEqual(cmd[cmd.index("--seen") + 1], "data/critical_run_seen_post_ids.txt")
        self.assertEqual(state["fetch"], "done")

    def test_fetch_fails_without_subs_instead_of_falling_back_to_niche_type(self):
        with self.assertRaises(SystemExit) as raised:
            pipeline.run_phase_fetch(make_args(), "critical_run", {})

        self.assertEqual(raised.exception.code, 1)


class SeedFactoryCriticalFixTests(unittest.TestCase):
    def test_failed_google_generation_preserves_existing_seed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_file = Path(tmp) / "seed_topics.txt"
            original = "# existing\ncrm software\n"
            seed_file.write_text(original, encoding="utf-8")

            with mock.patch.object(seed_factory, "OUTPUT_FILE", str(seed_file)), \
                 mock.patch.object(seed_factory.requests, "get", side_effect=RuntimeError("offline")), \
                 mock.patch.object(sys, "argv", ["seed_factory.py", "--source", "google", "--append"]), \
                 self.assertRaises(SystemExit) as raised:
                seed_factory.main()

            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(seed_file.read_text(encoding="utf-8"), original)


class RssMinerCriticalFixTests(unittest.TestCase):
    def test_search_mode_without_keywords_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_seed_file = Path(tmp) / "missing_seed_topics.txt"
            argv = [
                "rss_miner.py",
                "--mode", "urls",
                "--include_search",
                "--subs", "CRMSoftware",
            ]
            with mock.patch.object(rss_miner, "SEED_TOPICS_FILE", str(missing_seed_file)), \
                 mock.patch.object(sys, "argv", argv), \
                 self.assertRaises(SystemExit) as raised:
                rss_miner.main()

            self.assertEqual(raised.exception.code, 1)


class GapAnalysisCriticalFixTests(unittest.TestCase):
    def test_empty_input_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty_input = Path(tmp) / "empty.jsonl"
            empty_input.write_text("", encoding="utf-8")
            argv = ["gap_analysis.py", "--input", str(empty_input)]

            with mock.patch.object(sys, "argv", argv), \
                 contextlib.redirect_stdout(io.StringIO()), \
                 self.assertRaises(SystemExit) as raised:
                gap_analysis.main()

            self.assertEqual(raised.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
