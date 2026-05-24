import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def install_optional_dependency_stubs():
    if "feedparser" not in sys.modules:
        feedparser = types.ModuleType("feedparser")
        feedparser.FeedParserDict = dict
        feedparser.parse = lambda raw: SimpleNamespace(entries=[])
        sys.modules["feedparser"] = feedparser

    if "bs4" not in sys.modules:
        bs4 = types.ModuleType("bs4")

        class BeautifulSoup:
            def __init__(self, html, parser):
                self.html = html

            def get_text(self, separator=" ", strip=False):
                return (self.html or "").strip() if strip else (self.html or "")

        bs4.BeautifulSoup = BeautifulSoup
        sys.modules["bs4"] = bs4


install_optional_dependency_stubs()

import pipeline
import rss_miner
import seed_factory


def pipeline_args(**overrides):
    defaults = {
        "keywords": None,
        "skip_seed": False,
        "skip_scout": False,
        "skip_gap": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class PipelinePlanTests(unittest.TestCase):
    def test_fresh_full_run_plans_all_phases(self):
        phases = pipeline.build_phase_plan(pipeline_args(), {})

        self.assertEqual(phases, ["seed", "scout", "fetch", "normalize", "gap"])

    def test_cli_keywords_skip_seed_but_keep_downstream_phases(self):
        phases = pipeline.build_phase_plan(
            pipeline_args(keywords="crm tools,sales automation"),
            {"seed": "done"},
        )

        self.assertEqual(phases, ["scout", "fetch", "normalize", "gap"])


class PipelineSubprocessTests(unittest.TestCase):
    def test_fetch_passes_cli_inputs_and_uses_run_scoped_seen_file(self):
        args = SimpleNamespace(
            run_id="critical_run",
            niche_type="saas",
            subs=None,
            max_posts=7,
            prefix="best",
            keywords="crm tools,sales automation",
            only_pain_points=True,
        )
        state = {"scout_subs": "CRMSoftware,CRM"}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(pipeline, "PROJECT", tmp_path), \
                 mock.patch.object(pipeline, "DATA", tmp_path / "data"), \
                 mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                 mock.patch.object(
                     pipeline.subprocess,
                     "run",
                     return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
                 ) as run_mock:
                pipeline.run_phase_fetch(args, args.run_id, state)

        cmd = run_mock.call_args.args[0]
        kwargs = run_mock.call_args.kwargs

        self.assertNotIn("shell", kwargs)
        self.assertEqual(cmd[cmd.index("--subs") + 1], "CRMSoftware,CRM")
        self.assertEqual(cmd[cmd.index("--keywords") + 1], "crm tools,sales automation")
        self.assertEqual(cmd[cmd.index("--prefix") + 1], "best")
        self.assertIn("--only_pain_points", cmd)
        self.assertTrue(cmd[cmd.index("--seen") + 1].endswith("critical_run_seen_post_ids.txt"))
        self.assertEqual(state["fetch"], "done")

    def test_scout_failure_exits_without_marking_state_done(self):
        args = SimpleNamespace(
            keywords="crm tools,sales automation",
            max_seeds=5,
            subs=None,
        )
        state = {}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(pipeline, "PROJECT", tmp_path), \
                 mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                 mock.patch.object(
                     pipeline.subprocess,
                     "run",
                     return_value=SimpleNamespace(returncode=2, stdout="", stderr="bad args"),
                 ) as run_mock:
                with self.assertRaises(SystemExit) as raised:
                    pipeline.run_phase_scout(args, "critical_run", state)

        cmd = run_mock.call_args.args[0]
        kwargs = run_mock.call_args.kwargs

        self.assertEqual(raised.exception.code, 1)
        self.assertNotIn("shell", kwargs)
        self.assertEqual(cmd[2], "crm tools,sales automation")
        self.assertNotIn("scout", state)

    def test_scouted_subs_are_saved_for_fetch_resume(self):
        args = SimpleNamespace(
            keywords="crm tools",
            max_seeds=5,
            subs=None,
        )
        state = {}
        stdout = "To use with rss_miner: --subs CRMSoftware,CRM\n"

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(pipeline, "PROJECT", tmp_path), \
                 mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                 mock.patch.object(
                     pipeline.subprocess,
                     "run",
                     return_value=SimpleNamespace(returncode=0, stdout=stdout, stderr=""),
                 ):
                pipeline.run_phase_scout(args, "critical_run", state)

        self.assertEqual(args.subs, "CRMSoftware,CRM")
        self.assertEqual(state["scout_subs"], "CRMSoftware,CRM")
        self.assertEqual(state["scout"], "done")


class RssMinerTests(unittest.TestCase):
    def test_explicit_keywords_parse_with_prefix(self):
        self.assertEqual(
            rss_miner.parse_keyword_arg("crm tools, sales automation", prefix="best"),
            ["best crm tools", "best sales automation"],
        )


class SeedFactoryTests(unittest.TestCase):
    def test_failed_generation_does_not_overwrite_existing_seed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_path = Path(tmp) / "seed_topics.txt"
            seed_path.write_text("existing seed\n", encoding="utf-8")

            with mock.patch.object(seed_factory, "OUTPUT_FILE", str(seed_path)), \
                 mock.patch.object(sys, "argv", ["seed_factory.py", "--source", "google"]), \
                 mock.patch.object(seed_factory.SeedFactory, "harvest_google_taxonomy", return_value=None):
                with self.assertRaises(SystemExit) as raised:
                    seed_factory.main()

            self.assertEqual(raised.exception.code, 1)
            self.assertEqual(seed_path.read_text(encoding="utf-8"), "existing seed\n")


if __name__ == "__main__":
    unittest.main()
