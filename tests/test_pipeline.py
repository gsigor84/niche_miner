import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipeline


def make_args(**overrides):
    defaults = {
        "run_id": "test_run",
        "topic": "crm software",
        "keywords": None,
        "niche_type": "saas",
        "prefix": None,
        "subs": "CRMSoftware,CRM",
        "resume": False,
        "phase": None,
        "seed_count": 10,
        "max_seeds": 20,
        "max_posts": 10,
        "only_pain_points": False,
        "top_gaps": 20,
        "min_degree": 3,
        "viz": False,
        "input": None,
        "skip_seed": False,
        "skip_gap": False,
        "skip_scout": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class PipelineMainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.runs = self.root / "runs"
        self.data = self.root / "data"
        self.seed_file = self.root / "seed_topics.txt"

    def run_main(self, args, initial_state=None):
        calls = []

        if initial_state is not None:
            state_dir = self.runs / args.run_id
            state_dir.mkdir(parents=True, exist_ok=True)
            (state_dir / "state.json").write_text(json.dumps(initial_state))

        def fake_phase(name):
            def _phase(phase_args, run_id, state):
                calls.append(name)
                state[name] = "done"
                pipeline.save_run_state(run_id, state)

            return _phase

        with patch.object(pipeline, "DATA", self.data), \
             patch.object(pipeline, "RUNS", self.runs), \
             patch.object(pipeline, "SEED_FILE", self.seed_file), \
             patch.object(pipeline, "parse_args", return_value=args), \
             patch.object(pipeline, "run_phase_seed", fake_phase("seed")), \
             patch.object(pipeline, "run_phase_scout", fake_phase("scout")), \
             patch.object(pipeline, "run_phase_fetch", fake_phase("fetch")), \
             patch.object(pipeline, "run_phase_normalize", fake_phase("normalize")), \
             patch.object(pipeline, "run_phase_gap", fake_phase("gap")), \
             patch.object(pipeline.time, "sleep", lambda _seconds: None):
            pipeline.main()

        return calls

    def test_fresh_full_run_executes_all_phases_in_order(self):
        calls = self.run_main(make_args())

        self.assertEqual(calls, ["seed", "scout", "fetch", "normalize", "gap"])

    def test_keywords_run_skips_seed_but_continues_through_gap(self):
        calls = self.run_main(make_args(keywords="crm software, sales automation"))

        self.assertEqual(calls, ["scout", "fetch", "normalize", "gap"])

    def test_resume_continues_after_completed_phases(self):
        calls = self.run_main(
            make_args(resume=True),
            initial_state={"seed": "done", "scout": "done"},
        )

        self.assertEqual(calls, ["fetch", "normalize", "gap"])


class PipelinePhaseCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_fetch_passes_prefix_and_pain_filter_without_shell(self):
        args = make_args(prefix="best", only_pain_points=True)
        completed = argparse.Namespace(returncode=0, stdout="")

        with patch.object(pipeline, "RUNS", self.root / "runs"), \
             patch.object(pipeline.subprocess, "run", return_value=completed) as run_mock:
            pipeline.run_phase_fetch(args, args.run_id, {})

        run_mock.assert_called_once()
        cmd = run_mock.call_args.args[0]
        kwargs = run_mock.call_args.kwargs
        self.assertIsInstance(cmd, list)
        self.assertNotIn("shell", kwargs)
        self.assertIn("--prefix", cmd)
        self.assertIn("best", cmd)
        self.assertIn("--only_pain_points", cmd)

    def test_normalize_does_not_pass_fetch_only_pain_filter(self):
        args = make_args(only_pain_points=True)
        data_dir = self.root / "data"
        data_dir.mkdir()
        (data_dir / f"{args.run_id}_raw.jsonl").write_text("{}\n")

        with patch.object(pipeline, "DATA", data_dir), \
             patch.object(pipeline, "RUNS", self.root / "runs"), \
             patch.object(pipeline, "run", Mock()) as run_mock:
            pipeline.run_phase_normalize(args, args.run_id, {})

        cmd = run_mock.call_args.args[0]
        self.assertNotIn("--only_pain_points", cmd)


if __name__ == "__main__":
    unittest.main()
