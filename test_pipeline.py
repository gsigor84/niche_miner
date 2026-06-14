import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pipeline


def make_args(**overrides):
    defaults = {
        "run_id": "test_run",
        "topic": None,
        "keywords": None,
        "niche_type": "saas",
        "prefix": None,
        "subs": None,
        "resume": False,
        "phase": None,
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
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class PipelineTests(unittest.TestCase):
    def test_sequential_pipeline_runs_later_phases_after_state_updates(self):
        args = make_args()
        state = {}
        calls = []

        def phase(name):
            def _run(_args, _run_id, state):
                calls.append(name)
                state[name] = "done"
            return _run

        phase_funcs = {name: phase(name) for name in pipeline.PHASES}

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(pipeline, "RUNS", Path(tmp) / "runs"):
                with patch.object(pipeline, "PHASE_FUNCS", phase_funcs):
                    with patch.object(pipeline.time, "sleep", lambda _seconds: None):
                        ran = pipeline.run_sequential_pipeline(args, state)

        self.assertEqual(ran, pipeline.PHASES)
        self.assertEqual(calls, pipeline.PHASES)

    def test_scout_preserves_multi_word_keywords_and_saves_discovered_subs(self):
        args = make_args(max_seeds=2)
        state = {}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            seed_file = tmp_path / "seed_topics.txt"
            seed_file.write_text("confetti cannons\ndisco balls\n", encoding="utf-8")
            captured = {}

            def fake_run(cmd, **kwargs):
                captured["cmd"] = cmd
                captured["kwargs"] = kwargs
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    stdout="\n[SUCCESS] Top discovered subreddits: Nightlife, Ticketing\n"
                    "To use with rss_miner: --subs Nightlife,Ticketing\n",
                    stderr="",
                )

            with patch.object(pipeline, "SEED_FILE", seed_file):
                with patch.object(pipeline, "RUNS", tmp_path / "runs"):
                    with patch.object(pipeline.subprocess, "run", fake_run):
                        pipeline.run_phase_scout(args, args.run_id, state)

        self.assertEqual(captured["cmd"], [
            "python3",
            "scout_subreddits.py",
            "confetti cannons,disco balls",
            "--limit",
            "2",
        ])
        self.assertNotIn("shell", captured["kwargs"])
        self.assertEqual(state["subs"], "Nightlife,Ticketing")
        self.assertEqual(state["scout"], "done")

    def test_fetch_uses_discovered_subs_prefix_and_per_run_seen_file(self):
        args = make_args(prefix="best", max_posts=5)
        state = {"subs": "CRMSoftware,CRM"}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            captured = {}

            def fake_run(cmd, **kwargs):
                captured["cmd"] = cmd
                raw_path = Path(cmd[cmd.index("--out") + 1])
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text("{}\n", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0, stdout="saved\n", stderr="")

            with patch.object(pipeline, "DATA", tmp_path / "data"):
                with patch.object(pipeline, "RUNS", tmp_path / "runs"):
                    with patch.object(pipeline.subprocess, "run", fake_run):
                        pipeline.run_phase_fetch(args, args.run_id, state)

        cmd = captured["cmd"]
        self.assertEqual(cmd[cmd.index("--subs") + 1], "CRMSoftware,CRM")
        self.assertEqual(cmd[cmd.index("--prefix") + 1], "best")
        self.assertEqual(
            cmd[cmd.index("--seen") + 1],
            str(tmp_path / "data" / "test_run_seen_post_ids.txt"),
        )
        self.assertEqual(state["fetch"], "done")

    def test_normalize_command_does_not_pass_fetch_only_pain_flag(self):
        args = make_args()
        state = {}

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_dir = tmp_path / "data"
            data_dir.mkdir()
            (data_dir / "test_run_raw.jsonl").write_text("{}\n", encoding="utf-8")
            captured = {}

            def fake_run(cmd, _label, check=True):
                captured["cmd"] = cmd
                return subprocess.CompletedProcess(cmd, 0)

            with patch.object(pipeline, "DATA", data_dir):
                with patch.object(pipeline, "RUNS", tmp_path / "runs"):
                    with patch.object(pipeline, "run", fake_run):
                        pipeline.run_phase_normalize(args, args.run_id, state)

        self.assertNotIn("--only_pain_points", captured["cmd"])
        self.assertEqual(state["normalize"], "done")

    def test_parse_discovered_subs(self):
        output = "To use with rss_miner: --subs CRMSoftware,CRM\n"
        self.assertEqual(pipeline.parse_discovered_subs(output), "CRMSoftware,CRM")


if __name__ == "__main__":
    unittest.main()
