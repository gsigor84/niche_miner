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


WORKSPACE = Path(__file__).resolve().parents[1]


@contextlib.contextmanager
def temp_cwd():
    old_cwd = Path.cwd()
    with tempfile.TemporaryDirectory(dir=WORKSPACE) as tmp:
        os.chdir(tmp)
        try:
            yield Path(tmp)
        finally:
            os.chdir(old_cwd)


def install_rss_stubs():
    if "feedparser" not in sys.modules:
        sys.modules["feedparser"] = types.SimpleNamespace(
            FeedParserDict=dict,
            parse=lambda raw: types.SimpleNamespace(entries=[]),
        )
    if "bs4" not in sys.modules:
        class BeautifulSoup:
            def __init__(self, html, parser):
                self.html = html or ""

            def get_text(self, separator=" ", strip=False):
                return self.html.strip() if strip else self.html

        sys.modules["bs4"] = types.SimpleNamespace(BeautifulSoup=BeautifulSoup)


class SeedFactorySafetyTests(unittest.TestCase):
    def test_manual_default_does_not_wipe_existing_seed_file(self):
        import seed_factory

        with temp_cwd() as tmp:
            seed_file = tmp / "seed_topics.txt"
            seed_file.write_text("curated crm\n", encoding="utf-8")

            with mock.patch.object(sys, "argv", ["seed_factory.py"]):
                seed_factory.main()

            self.assertEqual(seed_file.read_text(encoding="utf-8"), "curated crm\n")

    def test_failed_llm_generation_preserves_existing_seed_file(self):
        import seed_factory

        with temp_cwd() as tmp:
            seed_file = tmp / "seed_topics.txt"
            seed_file.write_text("curated crm\n", encoding="utf-8")

            with mock.patch.object(sys, "argv", ["seed_factory.py", "--source", "llm", "--topic", "crm"]):
                with mock.patch.object(seed_factory.SeedFactory, "brainstorm_llm", return_value=0):
                    with self.assertRaises(SystemExit) as cm:
                        seed_factory.main()

            self.assertEqual(cm.exception.code, 1)
            self.assertEqual(seed_file.read_text(encoding="utf-8"), "curated crm\n")


class PipelineSafetyTests(unittest.TestCase):
    def test_fresh_pipeline_runs_all_pending_phases_after_state_updates(self):
        import pipeline

        calls = []

        def phase(name):
            def _run(args, run_id, state):
                calls.append(name)
                state[name] = "done"
                pipeline.save_run_state(run_id, state)
            return _run

        args = SimpleNamespace(
            run_id="fresh",
            resume=False,
            phase=None,
            topic=None,
            keywords=None,
            niche_type="saas",
            subs="CRM",
            viz=False,
            skip_seed=False,
            skip_scout=False,
            skip_gap=False,
        )

        with tempfile.TemporaryDirectory(dir=WORKSPACE) as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(pipeline, "DATA", tmp_path / "data"):
                with mock.patch.object(pipeline, "RUNS", tmp_path / "runs"):
                    with mock.patch.object(pipeline, "parse_args", return_value=args):
                        with mock.patch.object(pipeline, "run_phase_seed", phase("seed")):
                            with mock.patch.object(pipeline, "run_phase_scout", phase("scout")):
                                with mock.patch.object(pipeline, "run_phase_fetch", phase("fetch")):
                                    with mock.patch.object(pipeline, "run_phase_normalize", phase("normalize")):
                                        with mock.patch.object(pipeline, "run_phase_gap", phase("gap")):
                                            pipeline.main()

        self.assertEqual(calls, ["seed", "scout", "fetch", "normalize", "gap"])

    def test_fetch_uses_safe_argv_run_scoped_seen_and_cli_keywords(self):
        import pipeline

        args = SimpleNamespace(
            run_id="safe_fetch",
            niche_type="saas",
            subs=None,
            max_posts=5,
            max_seeds=2,
            prefix="best; touch injected",
            keywords="crm tools,sales automation",
            only_pain_points=True,
        )
        state = {}

        with tempfile.TemporaryDirectory(dir=WORKSPACE) as tmp:
            tmp_path = Path(tmp)
            data = tmp_path / "data"
            runs = tmp_path / "runs"
            (runs / args.run_id).mkdir(parents=True)
            (runs / args.run_id / "scout_subs.txt").write_text("CRMSoftware,CRM\n", encoding="utf-8")

            def fake_run(cmd, **kwargs):
                self.assertIsInstance(cmd, list)
                self.assertNotIn("shell", kwargs)
                data.mkdir(parents=True, exist_ok=True)
                (data / f"{args.run_id}_raw.jsonl").write_text('{"post_id":"abc123"}\n', encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="ok")

            with mock.patch.object(pipeline, "DATA", data):
                with mock.patch.object(pipeline, "RUNS", runs):
                    with mock.patch.object(pipeline.subprocess, "run", side_effect=fake_run) as run_mock:
                        pipeline.run_phase_fetch(args, args.run_id, state)

            cmd = run_mock.call_args.args[0]
            self.assertIn("--seen", cmd)
            self.assertIn(str((data / f"{args.run_id}_seen_post_ids.txt").relative_to(WORKSPACE)), cmd)
            self.assertIn("--keywords", cmd)
            self.assertIn(args.keywords, cmd)
            self.assertIn("--prefix", cmd)
            self.assertIn(args.prefix, cmd)
            self.assertEqual(state["fetch"], "done")

    def test_failed_fetch_does_not_mark_state_done(self):
        import pipeline

        args = SimpleNamespace(
            run_id="failed_fetch",
            niche_type="saas",
            subs="CRM",
            max_posts=5,
            max_seeds=2,
            prefix=None,
            keywords=None,
            only_pain_points=False,
        )
        state = {}

        with tempfile.TemporaryDirectory(dir=WORKSPACE) as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(pipeline, "DATA", tmp_path / "data"):
                with mock.patch.object(pipeline, "RUNS", tmp_path / "runs"):
                    with mock.patch.object(
                        pipeline.subprocess,
                        "run",
                        return_value=SimpleNamespace(returncode=2, stdout="boom"),
                    ):
                        with self.assertRaises(SystemExit):
                            pipeline.run_phase_fetch(args, args.run_id, state)

        self.assertNotIn("fetch", state)


class RssMinerKeywordTests(unittest.TestCase):
    def test_cli_keywords_override_seed_file_and_respect_max_keywords(self):
        install_rss_stubs()
        rss_miner = importlib.import_module("rss_miner")

        argv = [
            "rss_miner.py",
            "--mode",
            "urls",
            "--niche_type",
            "saas",
            "--subs",
            "CRM",
            "--include_search",
            "--keywords",
            "alpha,beta,gamma",
            "--max_keywords",
            "2",
        ]

        output = io.StringIO()
        with mock.patch.object(sys, "argv", argv):
            with mock.patch.object(rss_miner, "load_query_templates", return_value=["{kw} problem"]):
                with contextlib.redirect_stdout(output):
                    rss_miner.main()

        text = output.getvalue()
        self.assertIn("Total URLs: 2", text)
        self.assertIn("alpha+problem", text)
        self.assertIn("beta+problem", text)
        self.assertNotIn("gamma+problem", text)


if __name__ == "__main__":
    unittest.main()
