import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


class CriticalPipelineFixTests(unittest.TestCase):
    def test_fresh_keyword_run_continues_through_downstream_phases(self):
        import pipeline

        calls = []

        def mark_done(name):
            def _phase(args, run_id, state):
                calls.append(name)
                state[name] = "done"
            return _phase

        args = SimpleNamespace(
            run_id="critical_run",
            resume=False,
            phase=None,
            keywords="crm tools,sales automation",
            topic=None,
            niche_type="saas",
            subs=None,
            viz=False,
            skip_seed=False,
            skip_scout=False,
            skip_gap=False,
        )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(pipeline, "DATA", tmp_path / "data"), \
                 mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                 mock.patch.object(pipeline, "parse_args", return_value=args), \
                 mock.patch.object(pipeline, "run_phase_seed", mark_done("seed")), \
                 mock.patch.object(pipeline, "run_phase_scout", mark_done("scout")), \
                 mock.patch.object(pipeline, "run_phase_fetch", mark_done("fetch")), \
                 mock.patch.object(pipeline, "run_phase_normalize", mark_done("normalize")), \
                 mock.patch.object(pipeline, "run_phase_gap", mark_done("gap")), \
                 mock.patch.object(pipeline.time, "sleep"):
                pipeline.main()

        self.assertEqual(calls, ["scout", "fetch", "normalize", "gap"])

    def test_fetch_phase_passes_keywords_safely_and_run_scopes_seen_file(self):
        import pipeline

        args = SimpleNamespace(
            run_id="critical_run",
            keywords="crm tools,sales automation",
            prefix="best",
            only_pain_points=True,
            subs=None,
            niche_type="saas",
            max_posts=5,
        )
        state = {"subs": "CRM,Sales"}
        result = SimpleNamespace(returncode=0, stdout="ok", stderr="")

        with mock.patch.object(pipeline.subprocess, "run", return_value=result) as run_mock, \
             mock.patch.object(pipeline, "save_run_state") as save_mock:
            pipeline.run_phase_fetch(args, args.run_id, state)

        cmd = run_mock.call_args.args[0]
        kwargs = run_mock.call_args.kwargs
        self.assertIsInstance(cmd, list)
        self.assertNotIn("shell", kwargs)
        self.assertIn("--keywords", cmd)
        self.assertIn("crm tools,sales automation", cmd)
        self.assertIn("--prefix", cmd)
        self.assertIn("best", cmd)
        self.assertIn("--seen", cmd)
        self.assertIn("runs/critical_run/seen_post_ids.txt", cmd)
        self.assertIn("--only_pain_points", cmd)
        self.assertEqual(state["fetch"], "done")
        save_mock.assert_called_once()

    def test_failed_fetch_phase_is_not_marked_done(self):
        import pipeline

        args = SimpleNamespace(
            run_id="critical_run",
            keywords=None,
            prefix=None,
            only_pain_points=False,
            subs="CRM",
            niche_type="saas",
            max_posts=5,
        )
        state = {}
        result = SimpleNamespace(returncode=2, stdout="", stderr="network failed")

        with mock.patch.object(pipeline.subprocess, "run", return_value=result), \
             mock.patch.object(pipeline, "save_run_state") as save_mock, \
             self.assertRaises(SystemExit) as raised:
            pipeline.run_phase_fetch(args, args.run_id, state)

        self.assertEqual(raised.exception.code, 2)
        self.assertNotIn("fetch", state)
        save_mock.assert_not_called()


class CriticalProducerFixTests(unittest.TestCase):
    def import_rss_miner_with_optional_dependency_stubs(self):
        class DummySession:
            def __init__(self):
                self.headers = {}

        sys.modules.setdefault("feedparser", types.SimpleNamespace(
            FeedParserDict=dict,
            parse=lambda raw: types.SimpleNamespace(entries=[]),
        ))
        sys.modules.setdefault("requests", types.SimpleNamespace(Session=DummySession))
        sys.modules.setdefault("bs4", types.SimpleNamespace(
            BeautifulSoup=lambda html, parser: types.SimpleNamespace(get_text=lambda sep, strip: ""),
        ))
        return importlib.import_module("rss_miner")

    def test_rss_miner_uses_explicit_keywords_instead_of_seed_file(self):
        rss_miner = self.import_rss_miner_with_optional_dependency_stubs()
        captured = {}

        def fake_run_fetch(args):
            captured["keywords"] = args.keywords

        with mock.patch.object(sys, "argv", [
                "rss_miner.py",
                "--mode", "fetch",
                "--keywords", "crm tools,sales automation",
                "--prefix", "best",
                "--subs", "CRM",
                "--include_search",
            ]), \
             mock.patch.object(rss_miner, "load_query_templates", return_value=["{kw} review"]), \
             mock.patch.object(rss_miner, "run_fetch", side_effect=fake_run_fetch):
            rss_miner.main()

        self.assertEqual(captured["keywords"], ["best crm tools", "best sales automation"])

    def test_rss_miner_rejects_search_without_keywords(self):
        rss_miner = self.import_rss_miner_with_optional_dependency_stubs()

        with mock.patch.object(sys, "argv", [
                "rss_miner.py",
                "--mode", "urls",
                "--include_search",
                "--subs", "CRM",
            ]), \
             mock.patch.object(rss_miner, "load_query_templates", return_value=["{kw} review"]), \
             mock.patch.object(rss_miner, "load_keywords", return_value=[]), \
             self.assertRaises(SystemExit) as raised:
            rss_miner.main()

        self.assertEqual(raised.exception.code, 1)

    def test_seed_factory_preserves_existing_file_when_generation_adds_nothing(self):
        import seed_factory

        with tempfile.TemporaryDirectory() as tmp:
            seed_path = Path(tmp) / "seed_topics.txt"
            original = "# Existing\ncrm tools\n"
            seed_path.write_text(original, encoding="utf-8")
            factory = seed_factory.SeedFactory(str(seed_path))

            with mock.patch.object(seed_factory, "SeedFactory", return_value=factory), \
                 mock.patch.object(factory, "harvest_google_taxonomy"), \
                 mock.patch.object(sys, "argv", ["seed_factory.py", "--source", "google", "--append"]), \
                 self.assertRaises(SystemExit) as raised:
                seed_factory.main()

            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(seed_path.read_text(encoding="utf-8"), original)

    def test_empty_gap_input_exits_nonzero_and_writes_no_success_output(self):
        sys.modules.setdefault("networkx", types.SimpleNamespace())
        sys.modules.setdefault("numpy", types.SimpleNamespace())
        gap_analysis = importlib.import_module("gap_analysis")

        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "empty.jsonl"
            output_path = Path(tmp) / "gaps.json"
            input_path.write_text("", encoding="utf-8")

            with mock.patch.object(sys, "argv", [
                "gap_analysis.py",
                "--input", str(input_path),
                "--output", str(output_path),
            ]), self.assertRaises(SystemExit) as raised:
                gap_analysis.main()

            self.assertEqual(raised.exception.code, 1)
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
