import contextlib
import importlib
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


class DummySession:
    def __init__(self):
        self.headers = {}

    def get(self, *args, **kwargs):
        raise RuntimeError("network disabled in tests")


def _install_optional_dependency_stubs():
    sys.modules.setdefault(
        "feedparser",
        types.SimpleNamespace(
            FeedParserDict=dict,
            parse=lambda raw: types.SimpleNamespace(entries=[]),
        ),
    )
    sys.modules.setdefault(
        "requests",
        types.SimpleNamespace(
            Session=DummySession,
            get=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network disabled in tests")),
            post=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network disabled in tests")),
        ),
    )
    sys.modules.setdefault(
        "bs4",
        types.SimpleNamespace(
            BeautifulSoup=lambda html, parser: types.SimpleNamespace(
                get_text=lambda separator=" ", strip=True: ""
            )
        ),
    )


_install_optional_dependency_stubs()


class PipelineCriticalFixTests(unittest.TestCase):
    def setUp(self):
        import pipeline

        self.pipeline = importlib.reload(pipeline)
        self._old_argv = sys.argv[:]

    def tearDown(self):
        sys.argv = self._old_argv

    def _isolate_pipeline_paths(self, tmpdir):
        self.pipeline.RUNS = Path(tmpdir) / "runs"
        self.pipeline.DATA = Path(tmpdir) / "data"
        self.pipeline.SEED_FILE = Path(tmpdir) / "seed_topics.txt"
        self.pipeline.DATA.mkdir(parents=True, exist_ok=True)

    def test_fresh_full_run_evaluates_downstream_phases_after_state_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._isolate_pipeline_paths(tmpdir)
            calls = []

            def phase(name):
                def _run(args, run_id, state):
                    calls.append(name)
                    if name == "scout":
                        state["subs"] = "tickets"
                    state[name] = "done"
                    self.pipeline.save_run_state(run_id, state)

                return _run

            self.pipeline.run_phase_seed = phase("seed")
            self.pipeline.run_phase_scout = phase("scout")
            self.pipeline.run_phase_fetch = phase("fetch")
            self.pipeline.run_phase_normalize = phase("normalize")
            self.pipeline.run_phase_gap = phase("gap")

            sys.argv = [
                "pipeline.py",
                "--topic",
                "party tickets",
                "--niche_type",
                "events",
                "--run_id",
                "critical_full",
            ]
            with mock.patch.object(self.pipeline.time, "sleep", lambda seconds: None):
                self.pipeline.main()

            self.assertEqual(calls, ["seed", "scout", "fetch", "normalize", "gap"])

    def test_single_phase_rerun_preserves_existing_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._isolate_pipeline_paths(tmpdir)
            self.pipeline.save_run_state(
                "critical_resume",
                {"seed": "done", "scout": "done", "fetch": "done"},
            )

            def normalize(args, run_id, state):
                state["normalize"] = "done"
                self.pipeline.save_run_state(run_id, state)

            self.pipeline.run_phase_normalize = normalize

            sys.argv = [
                "pipeline.py",
                "--phase",
                "normalize",
                "--run_id",
                "critical_resume",
            ]
            with self.assertRaises(SystemExit) as raised:
                self.pipeline.main()
            self.assertEqual(raised.exception.code, 0)

            state = self.pipeline.load_run_state("critical_resume")
            self.assertEqual(state["seed"], "done")
            self.assertEqual(state["scout"], "done")
            self.assertEqual(state["fetch"], "done")
            self.assertEqual(state["normalize"], "done")

    def test_scout_failure_uses_argv_and_does_not_mark_phase_done(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._isolate_pipeline_paths(tmpdir)
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(cmd)
                return SimpleNamespace(returncode=2, stdout="", stderr="bad args")

            args = SimpleNamespace(keywords="party tickets", max_seeds=20, subs=None)
            with mock.patch.object(self.pipeline.subprocess, "run", fake_run):
                with self.assertRaises(SystemExit) as raised:
                    self.pipeline.run_phase_scout(args, "critical_scout", {})

            self.assertEqual(raised.exception.code, 2)
            self.assertIsInstance(calls[0], list)
            self.assertEqual(calls[0][2], "party tickets")
            self.assertEqual(self.pipeline.load_run_state("critical_scout").get("scout"), None)


class ToolCriticalFixTests(unittest.TestCase):
    def setUp(self):
        self._old_argv = sys.argv[:]

    def tearDown(self):
        sys.argv = self._old_argv

    def test_seed_factory_does_not_overwrite_existing_file_when_generation_fails(self):
        import seed_factory

        seed_factory = importlib.reload(seed_factory)
        with tempfile.TemporaryDirectory() as tmpdir:
            seed_file = Path(tmpdir) / "seed_topics.txt"
            original = "# existing\nparty tickets\n"
            seed_file.write_text(original, encoding="utf-8")
            factory = seed_factory.SeedFactory(str(seed_file))
            factory.brainstorm_llm = lambda *args, **kwargs: None

            sys.argv = ["seed_factory.py", "--source", "llm", "--topic", "tickets"]
            with mock.patch.object(seed_factory, "SeedFactory", return_value=factory):
                with self.assertRaises(SystemExit) as raised:
                    seed_factory.main()

            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(seed_file.read_text(encoding="utf-8"), original)

    def test_rss_miner_uses_cli_keywords_instead_of_seed_file(self):
        import rss_miner

        rss_miner = importlib.reload(rss_miner)
        sys.argv = [
            "rss_miner.py",
            "--mode",
            "urls",
            "--subs",
            "CRM",
            "--include_search",
            "--keywords",
            "crm tools,sales automation",
            "--max_keywords",
            "1",
        ]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rss_miner.main()

        rendered = output.getvalue()
        self.assertIn("crm+tools", rendered)
        self.assertNotIn("sales+automation", rendered)


if __name__ == "__main__":
    unittest.main()
