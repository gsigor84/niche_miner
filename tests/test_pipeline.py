import argparse
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pipeline


def make_args(**overrides):
    values = {
        "keywords": None,
        "skip_seed": False,
        "skip_scout": False,
        "skip_gap": False,
        "topic": None,
        "seed_count": 10,
        "max_seeds": 20,
        "niche_type": "saas",
        "subs": None,
        "max_posts": 10,
        "prefix": None,
        "only_pain_points": False,
        "run_id": "test_run",
        "input": None,
        "top_gaps": 20,
        "min_degree": 3,
        "viz": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class PipelinePlanningTests(unittest.TestCase):
    def test_fresh_full_run_plans_all_downstream_phases(self):
        args = make_args()

        phases = [name for name, _ in pipeline.planned_pipeline_phases(args, {})]

        self.assertEqual(phases, ["seed", "scout", "fetch", "normalize", "gap"])

    def test_resume_after_seed_and_scout_plans_remaining_phases(self):
        args = make_args()

        phases = [
            name
            for name, _ in pipeline.planned_pipeline_phases(
                args,
                {"seed": "done", "scout": "done"},
            )
        ]

        self.assertEqual(phases, ["fetch", "normalize", "gap"])

    def test_keywords_skip_seed_but_still_plan_fetch_normalize_gap(self):
        args = make_args(keywords="crm software,sales automation")

        phases = [name for name, _ in pipeline.planned_pipeline_phases(args, {})]

        self.assertEqual(phases, ["scout", "fetch", "normalize", "gap"])


class PipelinePhaseTests(unittest.TestCase):
    def test_fetch_uses_safe_argv_and_forwards_keywords(self):
        args = make_args(
            keywords="crm software,sales automation; echo injected",
            prefix="best",
            only_pain_points=True,
        )
        captured = {}

        def fake_run(cmd, label, **kwargs):
            captured["cmd"] = cmd
            captured["label"] = label

        with mock.patch.object(pipeline, "run", side_effect=fake_run), \
             mock.patch.object(pipeline, "save_run_state"):
            pipeline.run_phase_fetch(args, args.run_id, {"subs": "startups,Entrepreneur"})

        self.assertIsInstance(captured["cmd"], list)
        self.assertIn("--keywords", captured["cmd"])
        self.assertEqual(
            captured["cmd"][captured["cmd"].index("--keywords") + 1],
            "crm software,sales automation; echo injected",
        )
        self.assertIn("--subs", captured["cmd"])
        self.assertEqual(captured["cmd"][captured["cmd"].index("--subs") + 1], "startups,Entrepreneur")
        self.assertIn("--prefix", captured["cmd"])
        self.assertIn("--only_pain_points", captured["cmd"])

    def test_normalize_phase_does_not_require_only_pain_points_arg(self):
        args = argparse.Namespace(run_id="test_run")
        captured = {}

        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            (data_dir / "test_run_raw.jsonl").write_text('{"title":"ok"}\n', encoding="utf-8")

            def fake_run(cmd, label, **kwargs):
                captured["cmd"] = cmd

            with mock.patch.object(pipeline, "DATA", data_dir), \
                 mock.patch.object(pipeline, "run", side_effect=fake_run), \
                 mock.patch.object(pipeline, "save_run_state"):
                pipeline.run_phase_normalize(args, args.run_id, {})

        self.assertNotIn("--only_pain_points", captured["cmd"])

    def test_parse_scout_subs_extracts_discovered_targets(self):
        output = "noise\nTo use with rss_miner: --subs startups,SaaS,Entrepreneur\n"

        self.assertEqual(pipeline.parse_scout_subs(output), "startups,SaaS,Entrepreneur")


if __name__ == "__main__":
    unittest.main()
