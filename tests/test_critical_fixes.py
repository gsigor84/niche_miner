import contextlib
import importlib
import io
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


import pipeline
import seed_factory


@contextlib.contextmanager
def working_directory(path):
    old_cwd = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(old_cwd)


def import_rss_miner_with_stubs():
    if "rss_miner" in sys.modules:
        del sys.modules["rss_miner"]

    feedparser_stub = types.ModuleType("feedparser")
    feedparser_stub.FeedParserDict = dict
    feedparser_stub.parse = lambda raw: SimpleNamespace(entries=[])

    bs4_stub = types.ModuleType("bs4")

    class BeautifulSoup:
        def __init__(self, html, parser):
            self.html = html

        def get_text(self, separator=" ", strip=False):
            return self.html.strip() if strip else self.html

    bs4_stub.BeautifulSoup = BeautifulSoup

    with mock.patch.dict(sys.modules, {"feedparser": feedparser_stub, "bs4": bs4_stub}):
        return importlib.import_module("rss_miner")


class PipelineCriticalFixTests(unittest.TestCase):
    def test_fresh_pipeline_rechecks_state_between_phases(self):
        phases = []

        def fake_phase(name):
            def _run(args, run_id, state):
                phases.append(name)
                state[name] = "done"
            return _run

        argv = [
            "pipeline.py",
            "--topic",
            "demo topic",
            "--run_id",
            "unit_dynamic",
            "--skip_gap",
        ]
        with mock.patch.object(sys, "argv", argv), \
             mock.patch.object(pipeline, "run_phase_seed", fake_phase("seed")), \
             mock.patch.object(pipeline, "run_phase_scout", fake_phase("scout")), \
             mock.patch.object(pipeline, "run_phase_fetch", fake_phase("fetch")), \
             mock.patch.object(pipeline, "run_phase_normalize", fake_phase("normalize")), \
             mock.patch.object(pipeline, "save_run_state"):
            pipeline.main()

        self.assertEqual(phases, ["seed", "scout", "fetch", "normalize"])

    def test_fetch_uses_checked_argv_command_run_scoped_seen_and_cli_keywords(self):
        calls = []
        args = SimpleNamespace(
            niche_type="saas",
            subs=None,
            max_posts=10,
            run_id="unit_run",
            keywords="crm tools,sales automation",
            prefix="best",
            only_pain_points=True,
        )
        state = {"scout_subs": ["CRM", "sales"]}

        def fake_run(cmd, label, check=True):
            calls.append((cmd, label, check))

        with mock.patch.object(pipeline, "run", fake_run), \
             mock.patch.object(pipeline, "save_run_state"):
            pipeline.run_phase_fetch(args, args.run_id, state)

        cmd, label, check = calls[0]
        self.assertEqual(label, "PHASE 3: rss_miner")
        self.assertIs(cmd, calls[0][0])
        self.assertIn("--keywords", cmd)
        self.assertIn("crm tools,sales automation", cmd)
        self.assertIn("--prefix", cmd)
        self.assertIn("best", cmd)
        self.assertIn("--seen", cmd)
        self.assertIn("data/unit_run_seen_post_ids.txt", cmd)
        self.assertIn("--only_pain_points", cmd)
        self.assertEqual(cmd[cmd.index("--subs") + 1], "CRM,sales")
        self.assertTrue(check)
        self.assertEqual(state["fetch"], "done")

    def test_normalize_phase_does_not_pass_fetch_only_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "unit_raw.jsonl").write_text("{}\n", encoding="utf-8")
            args = SimpleNamespace(run_id="unit")
            state = {}
            calls = []

            def fake_run(cmd, label, check=True):
                calls.append(cmd)

            with mock.patch.object(pipeline, "DATA", data_dir), \
                 mock.patch.object(pipeline, "run", fake_run), \
                 mock.patch.object(pipeline, "save_run_state"):
                pipeline.run_phase_normalize(args, args.run_id, state)

            self.assertNotIn("--only_pain_points", calls[0])
            self.assertEqual(state["normalize"], "done")


class SeedFactoryCriticalFixTests(unittest.TestCase):
    def test_llm_failure_preserves_existing_seed_file_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_path = Path(tmp) / "seed_topics.txt"
            original = "existing seed\n"
            seed_path.write_text(original, encoding="utf-8")

            argv = ["seed_factory.py", "--source", "llm", "--topic", "crm", "--append"]
            with working_directory(tmp), \
                 mock.patch.object(sys, "argv", argv), \
                 mock.patch.object(seed_factory.requests, "post", side_effect=RuntimeError("ollama down")):
                with self.assertRaises(SystemExit) as cm:
                    seed_factory.main()

            self.assertNotEqual(cm.exception.code, 0)
            self.assertEqual(seed_path.read_text(encoding="utf-8"), original)


class RssMinerCriticalFixTests(unittest.TestCase):
    def test_cli_keywords_work_without_seed_file(self):
        rss_miner = import_rss_miner_with_stubs()
        with tempfile.TemporaryDirectory() as tmp:
            argv = [
                "rss_miner.py",
                "--mode",
                "urls",
                "--niche_type",
                "saas",
                "--subs",
                "CRM",
                "--keywords",
                "crm tools",
            ]
            stdout = io.StringIO()
            with working_directory(tmp), \
                 mock.patch.object(sys, "argv", argv), \
                 contextlib.redirect_stdout(stdout):
                rss_miner.main()

        output = stdout.getvalue()
        self.assertIn("Loaded 1 keywords", output)
        self.assertIn("crm+tools", output)

    def test_search_mode_without_keywords_exits_nonzero(self):
        rss_miner = import_rss_miner_with_stubs()
        with tempfile.TemporaryDirectory() as tmp:
            argv = ["rss_miner.py", "--mode", "urls", "--subs", "CRM"]
            with working_directory(tmp), mock.patch.object(sys, "argv", argv):
                with self.assertRaises(SystemExit) as cm:
                    rss_miner.main()

        self.assertNotEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
