import importlib
import io
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


def import_rss_miner():
    sys.modules.setdefault(
        "feedparser",
        types.SimpleNamespace(FeedParserDict=dict, parse=lambda raw: types.SimpleNamespace(entries=[])),
    )
    sys.modules.setdefault(
        "bs4",
        types.SimpleNamespace(
            BeautifulSoup=lambda html, parser: types.SimpleNamespace(
                get_text=lambda separator=" ", strip=True: ""
            )
        ),
    )
    return importlib.import_module("rss_miner")


class PipelineCriticalFixTests(unittest.TestCase):
    def test_fresh_run_schedules_all_remaining_phases(self):
        import pipeline

        calls = []

        def fake_phase(name):
            def _run(args, run_id, state):
                calls.append(name)
                state[name] = "done"
                pipeline.save_run_state(run_id, state)

            return _run

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            argv = [
                "pipeline.py",
                "--run_id",
                "critical",
                "--topic",
                "AI agents",
                "--niche_type",
                "saas",
            ]
            with mock.patch.object(pipeline, "PROJECT", root), \
                mock.patch.object(pipeline, "DATA", root / "data"), \
                mock.patch.object(pipeline, "RUNS", root / "runs"), \
                mock.patch.object(pipeline, "SEED_FILE", root / "seed_topics.txt"), \
                mock.patch.object(sys, "argv", argv), \
                mock.patch.object(pipeline.time, "sleep"), \
                mock.patch.object(pipeline, "run_phase_seed", fake_phase("seed")), \
                mock.patch.object(pipeline, "run_phase_scout", fake_phase("scout")), \
                mock.patch.object(pipeline, "run_phase_fetch", fake_phase("fetch")), \
                mock.patch.object(pipeline, "run_phase_normalize", fake_phase("normalize")), \
                mock.patch.object(pipeline, "run_phase_gap", fake_phase("gap")):
                with redirect_stdout(io.StringIO()):
                    pipeline.main()

        self.assertEqual(calls, ["seed", "scout", "fetch", "normalize", "gap"])

    def test_fetch_uses_run_scoped_seen_and_cli_keywords(self):
        import pipeline

        recorded = {}

        def fake_run(cmd, label, check=True):
            recorded["cmd"] = cmd
            return SimpleNamespace(returncode=0)

        args = SimpleNamespace(
            run_id="critical",
            prefix="best",
            niche_type="saas",
            subs=None,
            max_posts=25,
            keywords="party tickets,festival passes",
            only_pain_points=True,
        )
        state = {"scouted_subs": "events,ticketing"}

        with mock.patch.object(pipeline, "run", fake_run):
            pipeline.run_phase_fetch(args, args.run_id, state)

        cmd = recorded["cmd"]
        self.assertIn("--seen", cmd)
        self.assertIn("data/critical_seen_post_ids.txt", cmd)
        self.assertIn("--keywords", cmd)
        self.assertIn("party tickets,festival passes", cmd)
        self.assertIn("--prefix", cmd)
        self.assertIn("best", cmd)
        self.assertIn("--only_pain_points", cmd)
        self.assertIn("--subs", cmd)
        self.assertIn("events,ticketing", cmd)
        self.assertEqual(state["fetch"], "done")

    def test_normalize_phase_does_not_reference_fetch_only_flags(self):
        import pipeline

        recorded = {}

        def fake_run(cmd, label, check=True):
            recorded["cmd"] = cmd
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = root / "data"
            data.mkdir()
            (data / "critical_raw.jsonl").write_text("{}\n", encoding="utf-8")
            args = SimpleNamespace(run_id="critical")
            state = {}

            with mock.patch.object(pipeline, "DATA", data), \
                mock.patch.object(pipeline, "RUNS", root / "runs"), \
                mock.patch.object(pipeline, "run", fake_run):
                pipeline.run_phase_normalize(args, args.run_id, state)

        self.assertNotIn("--only_pain_points", recorded["cmd"])
        self.assertEqual(state["normalize"], "done")


class SeedFactoryCriticalFixTests(unittest.TestCase):
    def test_failed_google_harvest_does_not_overwrite_existing_seed_file(self):
        import seed_factory

        with tempfile.TemporaryDirectory() as td:
            seed_file = Path(td) / "seed_topics.txt"
            original = "# existing\ncrm software\n"
            seed_file.write_text(original, encoding="utf-8")
            argv = ["seed_factory.py", "--source", "google"]

            with mock.patch.object(seed_factory, "OUTPUT_FILE", str(seed_file)), \
                mock.patch.object(sys, "argv", argv), \
                mock.patch.object(seed_factory.requests, "get", side_effect=RuntimeError("network down")):
                with self.assertRaises(SystemExit) as cm:
                    seed_factory.main()

            self.assertEqual(cm.exception.code, 1)
            self.assertEqual(seed_file.read_text(encoding="utf-8"), original)


class RssMinerCriticalFixTests(unittest.TestCase):
    def test_search_fetch_without_keywords_exits_nonzero(self):
        rss_miner = import_rss_miner()

        with tempfile.TemporaryDirectory() as td:
            missing_seed = Path(td) / "missing_seed_topics.txt"
            out = Path(td) / "out.jsonl"
            argv = [
                "rss_miner.py",
                "--mode",
                "fetch",
                "--seed_file",
                str(missing_seed),
                "--out",
                str(out),
            ]

            with mock.patch.object(sys, "argv", argv):
                with self.assertRaises(SystemExit) as cm:
                    with redirect_stdout(io.StringIO()):
                        rss_miner.main()

            self.assertEqual(cm.exception.code, 1)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
