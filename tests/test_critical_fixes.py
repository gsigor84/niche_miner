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


class PipelineCriticalFixTests(unittest.TestCase):
    def test_normalize_phase_does_not_reference_missing_only_pain_points(self):
        import pipeline

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            raw = tmp_path / "case_raw.jsonl"
            raw.write_text('{"title": "x"}\n', encoding="utf-8")
            state = {}
            captured = {}

            def fake_run(cmd, label, check=True):
                captured["cmd"] = cmd
                return SimpleNamespace(returncode=0)

            args = SimpleNamespace(run_id="case")
            with mock.patch.object(pipeline, "DATA", tmp_path), \
                    mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                    mock.patch.object(pipeline, "run", side_effect=fake_run):
                pipeline.run_phase_normalize(args, "case", state)

        self.assertEqual(state["normalize"], "done")
        self.assertNotIn("--only_pain_points", captured["cmd"])
        self.assertIn("--dedupe", captured["cmd"])

    def test_scout_uses_argv_and_persists_discovered_subreddits(self):
        import pipeline

        state = {}
        args = SimpleNamespace(
            keywords="crm tools,sales automation; echo injected",
            max_seeds=5,
            subs=None,
        )
        result = SimpleNamespace(
            returncode=0,
            stdout="To use with rss_miner: --subs CRMSoftware,CRM\n",
            stderr="",
        )

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(pipeline, "RUNS", Path(tmp) / "runs"), \
                    mock.patch.object(pipeline.subprocess, "run", return_value=result) as run_mock:
                pipeline.run_phase_scout(args, "case", state)

        call = run_mock.call_args
        self.assertIsInstance(call.args[0], list)
        self.assertNotIn("shell", call.kwargs)
        self.assertEqual(state["subs"], "CRMSoftware,CRM")
        self.assertEqual(state["scout"], "done")

    def test_fetch_forwards_keywords_prefix_subs_and_run_scoped_seen_file(self):
        import pipeline

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            raw = tmp_path / "case_raw.jsonl"
            state = {"subs": "CRMSoftware,CRM"}
            captured = {}

            def fake_run(cmd, label, check=True):
                captured["cmd"] = cmd
                raw.write_text('{"post_id": "abc123"}\n', encoding="utf-8")
                return SimpleNamespace(returncode=0)

            args = SimpleNamespace(
                run_id="case",
                niche_type="saas",
                max_posts=10,
                subs=None,
                keywords="crm tools,sales automation",
                prefix="best",
                only_pain_points=True,
            )
            with mock.patch.object(pipeline, "DATA", tmp_path), \
                    mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                    mock.patch.object(pipeline, "run", side_effect=fake_run):
                pipeline.run_phase_fetch(args, "case", state)

        cmd = captured["cmd"]
        self.assertEqual(state["fetch"], "done")
        self.assertEqual(cmd[cmd.index("--subs") + 1], "CRMSoftware,CRM")
        self.assertEqual(cmd[cmd.index("--keywords") + 1], "crm tools,sales automation")
        self.assertEqual(cmd[cmd.index("--prefix") + 1], "best")
        self.assertEqual(Path(cmd[cmd.index("--seen") + 1]).name, "case_seen_post_ids.txt")
        self.assertIn("--only_pain_points", cmd)


class SeedFactoryCriticalFixTests(unittest.TestCase):
    def test_llm_failure_does_not_overwrite_existing_seed_file(self):
        import seed_factory

        with tempfile.TemporaryDirectory() as tmp:
            seed_file = Path(tmp) / "seed_topics.txt"
            original = "# existing\ncrm tools\n"
            seed_file.write_text(original, encoding="utf-8")
            argv = [
                "seed_factory.py",
                "--source", "llm",
                "--topic", "crm",
                "--output", str(seed_file),
            ]

            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(seed_factory.requests, "post", side_effect=RuntimeError("down"), create=True):
                with self.assertRaises(SystemExit) as cm:
                    seed_factory.main()

            self.assertNotEqual(cm.exception.code, 0)
            self.assertEqual(seed_file.read_text(encoding="utf-8"), original)


class RssMinerCriticalFixTests(unittest.TestCase):
    def test_cli_keywords_are_used_for_generated_urls(self):
        sys.modules.setdefault("feedparser", types.SimpleNamespace(FeedParserDict=dict, parse=lambda raw: None))
        sys.modules.setdefault("requests", types.SimpleNamespace(Session=lambda: types.SimpleNamespace(headers={}, get=None)))
        sys.modules.setdefault("bs4", types.SimpleNamespace(BeautifulSoup=lambda html, parser: types.SimpleNamespace(get_text=lambda sep, strip: "")))
        rss_miner = importlib.import_module("rss_miner")

        argv = [
            "rss_miner.py",
            "--mode", "urls",
            "--niche_type", "saas",
            "--subs", "CRM",
            "--include_search",
            "--keywords", "crm tools,sales automation",
            "--prefix", "best",
        ]
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(stdout):
            rss_miner.main()

        output = stdout.getvalue()
        self.assertIn("best+crm+tools", output)
        self.assertIn("best+sales+automation", output)


if __name__ == "__main__":
    unittest.main()
