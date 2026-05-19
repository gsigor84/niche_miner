import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pipeline


class PipelineRegressionTests(unittest.TestCase):
    def test_full_run_executes_downstream_phases_in_dependency_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data = tmp_path / "data"
            runs = tmp_path / "runs"
            seed_file = tmp_path / "seed_topics.txt"
            labels = []

            def fake_run(cmd, label, check=True):
                labels.append(label)
                data.mkdir(parents=True, exist_ok=True)
                if label == "PHASE 1: seed_factory":
                    seed_file.write_text("party tickets\n", encoding="utf-8")
                elif label == "PHASE 3: rss_miner":
                    (data / "full_run_raw.jsonl").write_text(
                        json.dumps({"title": "post", "post_id": "abcde", "comments": []}) + "\n",
                        encoding="utf-8",
                    )
                elif label == "PHASE 4: normalize":
                    (data / "full_run_normalized.jsonl").write_text(
                        json.dumps({"title": "post", "summary": "", "comments": []}) + "\n",
                        encoding="utf-8",
                    )
                return SimpleNamespace(returncode=0)

            argv = ["pipeline.py", "--run_id", "full_run", "--topic", "party tickets"]
            with patch.object(sys, "argv", argv), \
                 patch.object(pipeline, "DATA", data), \
                 patch.object(pipeline, "RUNS", runs), \
                 patch.object(pipeline, "SEED_FILE", seed_file), \
                 patch.object(pipeline, "run", side_effect=fake_run), \
                 patch.object(pipeline.time, "sleep"):
                pipeline.main()

            self.assertEqual(
                labels,
                [
                    "PHASE 1: seed_factory",
                    "PHASE 2: scout_subreddits",
                    "PHASE 3: rss_miner",
                    "PHASE 4: normalize",
                    "PHASE 5: gap_analysis",
                ],
            )
            state = json.loads((runs / "full_run" / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(
                state,
                {"seed": "done", "scout": "done", "fetch": "done", "normalize": "done", "gap": "done"},
            )

    def test_fetch_forwards_cli_keywords_and_prefix_as_argv(self):
        args = SimpleNamespace(
            niche_type="events",
            subs="tickets",
            max_posts=5,
            run_id="kw_run",
            keywords="party tickets,ai agents",
            prefix="cheap",
            only_pain_points=False,
        )
        state = {}
        calls = []

        def fake_run(cmd, label, check=True):
            calls.append(cmd)
            return SimpleNamespace(returncode=0)

        with patch.object(pipeline, "run", side_effect=fake_run), \
             patch.object(pipeline, "save_run_state"):
            pipeline.run_phase_fetch(args, "kw_run", state)

        cmd = calls[0]
        self.assertIsInstance(cmd, list)
        self.assertIn("--keywords", cmd)
        self.assertEqual(cmd[cmd.index("--keywords") + 1], "party tickets,ai agents")
        self.assertIn("--prefix", cmd)
        self.assertEqual(cmd[cmd.index("--prefix") + 1], "cheap")
        self.assertEqual(state["fetch"], "done")

    def test_failed_fetch_does_not_mark_state_done(self):
        args = SimpleNamespace(
            niche_type="events",
            subs="tickets",
            max_posts=5,
            run_id="kw_run",
            keywords=None,
            prefix=None,
            only_pain_points=False,
        )
        state = {}

        def fail_run(cmd, label, check=True):
            raise SystemExit(1)

        with patch.object(pipeline, "run", side_effect=fail_run), \
             patch.object(pipeline, "save_run_state"):
            with self.assertRaises(SystemExit):
                pipeline.run_phase_fetch(args, "kw_run", state)

        self.assertNotIn("fetch", state)


if __name__ == "__main__":
    unittest.main()
