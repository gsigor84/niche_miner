import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pipeline


def make_args(**overrides):
    defaults = {
        "keywords": None,
        "skip_seed": False,
        "skip_scout": False,
        "skip_gap": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class PipelineSchedulingTests(unittest.TestCase):
    def test_fresh_run_executes_downstream_phases_after_state_updates(self):
        calls = []

        def make_phase(name):
            def phase(args, run_id, state):
                calls.append(name)
                state[name] = "done"

            return phase

        runners = {name: make_phase(name) for name in pipeline.PHASES}

        with mock.patch.object(pipeline, "phase_runners", return_value=runners), mock.patch.object(
            pipeline.time, "sleep"
        ):
            executed = pipeline.run_sequential_pipeline(make_args(), "run-1", {})

        self.assertEqual(executed, pipeline.PHASES)
        self.assertEqual(calls, pipeline.PHASES)

    def test_keywords_skip_seed_but_continue_pipeline(self):
        calls = []

        def make_phase(name):
            def phase(args, run_id, state):
                calls.append(name)
                state[name] = "done"

            return phase

        runners = {name: make_phase(name) for name in pipeline.PHASES}

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            pipeline, "RUNS", Path(tmpdir)
        ), mock.patch.object(pipeline, "phase_runners", return_value=runners), mock.patch.object(
            pipeline.time, "sleep"
        ):
            state = {}
            executed = pipeline.run_sequential_pipeline(
                make_args(keywords="crm software, sales automation"), "run-2", state
            )
            saved_state = json.loads((Path(tmpdir) / "run-2" / "state.json").read_text())

        self.assertEqual(executed, ["scout", "fetch", "normalize", "gap"])
        self.assertEqual(calls, ["scout", "fetch", "normalize", "gap"])
        self.assertEqual(state["seed"], "done")
        self.assertEqual(saved_state["seed"], "done")

    def test_resume_from_fetch_continues_normalize_and_gap(self):
        calls = []

        def make_phase(name):
            def phase(args, run_id, state):
                calls.append(name)
                state[name] = "done"

            return phase

        runners = {name: make_phase(name) for name in pipeline.PHASES}
        state = {"seed": "done", "scout": "done", "fetch": "done"}

        with mock.patch.object(pipeline, "phase_runners", return_value=runners), mock.patch.object(
            pipeline.time, "sleep"
        ):
            executed = pipeline.run_sequential_pipeline(make_args(), "run-3", state)

        self.assertEqual(executed, ["normalize", "gap"])
        self.assertEqual(calls, ["normalize", "gap"])


if __name__ == "__main__":
    unittest.main()
