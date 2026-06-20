import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import pipeline
import seed_factory


def install_optional_dependency_stubs():
    """Allow importing RSS modules in minimal test environments."""
    if "feedparser" not in sys.modules:
        sys.modules["feedparser"] = types.SimpleNamespace(
            FeedParserDict=dict,
            parse=lambda raw: types.SimpleNamespace(entries=[]),
        )

    if "bs4" not in sys.modules:
        class DummySoup:
            def __init__(self, html, parser):
                self.html = html or ""

            def get_text(self, separator=" ", strip=True):
                return self.html.strip() if strip else self.html

        sys.modules["bs4"] = types.SimpleNamespace(BeautifulSoup=DummySoup)

    if "requests" not in sys.modules:
        class DummySession:
            def __init__(self):
                self.headers = {}

            def get(self, *args, **kwargs):
                raise RuntimeError("network disabled in tests")

        sys.modules["requests"] = types.SimpleNamespace(
            Session=DummySession,
            get=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network disabled in tests")),
            post=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("network disabled in tests")),
        )


class PipelineCriticalFixTests(unittest.TestCase):
    def test_full_run_executes_downstream_phases_in_same_invocation(self):
        calls = []

        def make_phase(name):
            def phase(args, run_id, state):
                calls.append(name)
                state[name] = "done"
                pipeline.save_run_state(run_id, state)
            return phase

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with mock.patch.object(pipeline, "DATA", tmp_path / "data"), \
                 mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                 mock.patch.object(pipeline, "SEED_FILE", tmp_path / "seed_topics.txt"), \
                 mock.patch.object(pipeline, "run_phase_seed", make_phase("seed")), \
                 mock.patch.object(pipeline, "run_phase_scout", make_phase("scout")), \
                 mock.patch.object(pipeline, "run_phase_fetch", make_phase("fetch")), \
                 mock.patch.object(pipeline, "run_phase_normalize", make_phase("normalize")), \
                 mock.patch.object(pipeline.time, "sleep", return_value=None), \
                 mock.patch.object(sys, "argv", [
                     "pipeline.py",
                     "--topic", "CRM",
                     "--run_id", "critical_run",
                     "--skip_gap",
                 ]):
                pipeline.main()

        self.assertEqual(calls, ["seed", "scout", "fetch", "normalize"])

    def test_single_phase_preserves_existing_state_without_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_dir = tmp_path / "runs" / "critical_run"
            run_dir.mkdir(parents=True)
            (run_dir / "state.json").write_text(
                json.dumps({"seed": "done", "scout": "done"}),
                encoding="utf-8",
            )

            def phase_gap(args, run_id, state):
                state["gap"] = "done"
                pipeline.save_run_state(run_id, state)

            with mock.patch.object(pipeline, "DATA", tmp_path / "data"), \
                 mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                 mock.patch.object(pipeline, "run_phase_gap", phase_gap), \
                 mock.patch.object(sys, "argv", [
                     "pipeline.py",
                     "--phase", "gap",
                     "--run_id", "critical_run",
                 ]):
                with self.assertRaises(SystemExit) as cm:
                    pipeline.main()

            self.assertEqual(cm.exception.code, 0)
            state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state, {"seed": "done", "scout": "done", "gap": "done"})

    def test_fetch_phase_uses_safe_argv_and_run_scoped_inputs(self):
        captured = {}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_dir = tmp_path / "data"

            def fake_run(cmd, label):
                captured["cmd"] = cmd
                data_dir.mkdir(parents=True, exist_ok=True)
                (data_dir / "critical_run_raw.jsonl").write_text("{}\n", encoding="utf-8")
                return types.SimpleNamespace(returncode=0)

            args = types.SimpleNamespace(
                run_id="critical_run",
                niche_type="saas",
                max_posts=5,
                subs=None,
                keywords="crm tools,sales automation",
                prefix="best",
                only_pain_points=True,
            )
            state = {"subs": "CRM,Sales"}

            with mock.patch.object(pipeline, "DATA", data_dir), \
                 mock.patch.object(pipeline, "RUNS", tmp_path / "runs"), \
                 mock.patch.object(pipeline, "run", fake_run):
                pipeline.run_phase_fetch(args, "critical_run", state)

        cmd = captured["cmd"]
        self.assertIsInstance(cmd, list)
        self.assertNotIn("shell=True", " ".join(cmd))
        self.assertEqual(cmd[cmd.index("--subs") + 1], "CRM,Sales")
        self.assertEqual(cmd[cmd.index("--keywords") + 1], "crm tools,sales automation")
        self.assertEqual(cmd[cmd.index("--prefix") + 1], "best")
        self.assertIn("critical_run_seen_post_ids.txt", cmd[cmd.index("--seen") + 1])
        self.assertEqual(state["fetch"], "done")


class SeedFactoryCriticalFixTests(unittest.TestCase):
    def test_failed_llm_generation_does_not_overwrite_existing_seed_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            seed_path = Path(tmp) / "seed_topics.txt"
            seed_path.write_text("existing seed\n", encoding="utf-8")

            with mock.patch.object(sys, "argv", [
                     "seed_factory.py",
                     "--source", "llm",
                     "--topic", "CRM",
                     "--output", str(seed_path),
                 ]), \
                 mock.patch.object(
                     seed_factory.requests,
                     "post",
                     side_effect=RuntimeError("ollama unavailable"),
                     create=True,
                 ):
                exit_code = seed_factory.main()

            self.assertEqual(exit_code, 1)
            self.assertEqual(seed_path.read_text(encoding="utf-8"), "existing seed\n")


class RssMinerCriticalFixTests(unittest.TestCase):
    def test_search_mode_with_missing_seed_file_exits_nonzero(self):
        install_optional_dependency_stubs()
        rss_miner = importlib.import_module("rss_miner")
        rss_miner = importlib.reload(rss_miner)

        with tempfile.TemporaryDirectory() as tmp:
            missing_seed = Path(tmp) / "missing_seed_topics.txt"
            with mock.patch.object(sys, "argv", [
                "rss_miner.py",
                "--mode", "urls",
                "--seed_file", str(missing_seed),
            ]):
                with self.assertRaises(SystemExit) as cm:
                    rss_miner.main()

        self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
