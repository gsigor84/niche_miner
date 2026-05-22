import importlib
import os
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


@contextmanager
def patched_attr(obj, name, value):
    original = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield
    finally:
        setattr(obj, name, original)


class PipelineCriticalFixTests(unittest.TestCase):
    def test_fresh_pipeline_run_executes_all_unfinished_phases(self):
        import pipeline

        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            tmp_path = Path(tmp)

            def phase(name):
                def _run(args, run_id, state):
                    calls.append(name)
                    state[name] = "done"
                    pipeline.save_run_state(run_id, state)
                return _run

            patches = [
                mock.patch.object(pipeline, "DATA", tmp_path / "data"),
                mock.patch.object(pipeline, "RUNS", tmp_path / "runs"),
                mock.patch.object(pipeline, "run_phase_seed", phase("seed")),
                mock.patch.object(pipeline, "run_phase_scout", phase("scout")),
                mock.patch.object(pipeline, "run_phase_fetch", phase("fetch")),
                mock.patch.object(pipeline, "run_phase_normalize", phase("normalize")),
                mock.patch.object(pipeline, "run_phase_gap", phase("gap")),
                mock.patch.object(sys, "argv", [
                    "pipeline.py",
                    "--run_id", "critical_run",
                    "--topic", "party tickets",
                ]),
            ]
            with contextmanager_from_patches(patches):
                pipeline.main()

            self.assertEqual(calls, ["seed", "scout", "fetch", "normalize", "gap"])

    def test_normalize_phase_does_not_reference_missing_pain_point_arg(self):
        import pipeline

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_dir = tmp_path / "data"
            data_dir.mkdir()
            (data_dir / "run_raw.jsonl").write_text("{}", encoding="utf-8")
            captured = {}

            def fake_run(cmd, label, check=True):
                captured["cmd"] = cmd
                return types.SimpleNamespace(returncode=0)

            args = types.SimpleNamespace(run_id="run")
            state = {}
            with mock.patch.object(pipeline, "DATA", data_dir), \
                    mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                    mock.patch.object(pipeline, "run", fake_run):
                pipeline.run_phase_normalize(args, "run", state)

            self.assertNotIn("--only_pain_points", captured["cmd"])
            self.assertEqual(state["normalize"], "done")

    def test_scout_uses_single_keyword_argument_and_records_discovered_subs(self):
        import pipeline

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return types.SimpleNamespace(
                returncode=0,
                stdout="\n[SUCCESS] Top discovered subreddits: Concerts, EDM\n"
                       "To use with rss_miner: --subs Concerts,EDM\n",
                stderr="",
            )

        args = types.SimpleNamespace(
            subs=None,
            keywords="party tickets,nightlife events",
            max_seeds=5,
        )
        state = {}
        with mock.patch.object(pipeline.subprocess, "run", fake_run), \
                mock.patch.object(pipeline, "save_run_state", lambda *a, **k: None):
            pipeline.run_phase_scout(args, "run", state)

        self.assertEqual(captured["cmd"][:3], ["python3", "scout_subreddits.py", "party tickets,nightlife events"])
        self.assertNotIn("shell", captured["kwargs"])
        self.assertEqual(state["subs"], "Concerts,EDM")
        self.assertEqual(state["scout"], "done")

    def test_fetch_uses_direct_keywords_prefix_and_run_scoped_seen_file(self):
        import pipeline

        captured = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return types.SimpleNamespace(returncode=0, stdout="Done.", stderr="")

        args = types.SimpleNamespace(
            niche_type="events",
            max_posts=10,
            run_id="critical_run",
            subs=None,
            prefix="local",
            keywords="party tickets",
            only_pain_points=True,
        )
        state = {"subs": "Concerts,EDM"}
        with mock.patch.object(pipeline.subprocess, "run", fake_run), \
                mock.patch.object(pipeline, "save_run_state", lambda *a, **k: None):
            pipeline.run_phase_fetch(args, "critical_run", state)

        cmd = captured["cmd"]
        self.assertNotIn("shell", captured["kwargs"])
        self.assertIn("--subs", cmd)
        self.assertEqual(cmd[cmd.index("--subs") + 1], "Concerts,EDM")
        self.assertIn("--keywords", cmd)
        self.assertEqual(cmd[cmd.index("--keywords") + 1], "party tickets")
        self.assertIn("--prefix", cmd)
        self.assertIn("--only_pain_points", cmd)
        self.assertIn("--seen", cmd)
        self.assertEqual(cmd[cmd.index("--seen") + 1], "data/critical_run_seen_post_ids.txt")
        self.assertEqual(state["fetch"], "done")


class SeedFactoryCriticalFixTests(unittest.TestCase):
    def test_failed_seed_generation_does_not_overwrite_existing_seed_file(self):
        import seed_factory

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            seed_file = tmp_path / "seed_topics.txt"
            seed_file.write_text("valuable seed\n", encoding="utf-8")
            old_cwd = os.getcwd()
            os.chdir(tmp_path)
            try:
                with mock.patch.object(seed_factory.SeedFactory, "harvest_google_taxonomy", lambda self: None), \
                        mock.patch.object(sys, "argv", ["seed_factory.py", "--source", "google"]):
                    with self.assertRaises(SystemExit) as cm:
                        seed_factory.main()
                self.assertNotEqual(cm.exception.code, 0)
                self.assertEqual(seed_file.read_text(encoding="utf-8"), "valuable seed\n")
            finally:
                os.chdir(old_cwd)


class RssMinerCriticalFixTests(unittest.TestCase):
    def test_cli_keywords_bypass_seed_file_and_receive_prefix(self):
        rss_miner = import_rss_miner_with_stubs()

        self.assertEqual(
            rss_miner.parse_keywords("party tickets, nightlife", prefix="local"),
            ["local party tickets", "local nightlife"],
        )


@contextmanager
def contextmanager_from_patches(patches):
    exits = []
    try:
        for patch in patches:
            exits.append(patch.__enter__)
            patch.__enter__()
        yield
    finally:
        for patch in reversed(patches):
            patch.__exit__(None, None, None)


def import_rss_miner_with_stubs():
    if "rss_miner" in sys.modules:
        return sys.modules["rss_miner"]

    feedparser = types.ModuleType("feedparser")
    feedparser.FeedParserDict = dict
    feedparser.parse = lambda raw: types.SimpleNamespace(entries=[])
    sys.modules.setdefault("feedparser", feedparser)

    bs4 = types.ModuleType("bs4")

    class FakeBeautifulSoup:
        def __init__(self, html, parser):
            self.html = html or ""

        def get_text(self, separator, strip=False):
            return self.html.strip() if strip else self.html

    bs4.BeautifulSoup = FakeBeautifulSoup
    sys.modules.setdefault("bs4", bs4)

    return importlib.import_module("rss_miner")


if __name__ == "__main__":
    unittest.main()
