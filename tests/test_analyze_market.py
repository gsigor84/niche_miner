import tempfile
import unittest
from pathlib import Path
from unittest import mock

import analyze_market


class AnalyzeMarketTests(unittest.TestCase):
    def test_generate_report_analyzes_every_thread(self):
        threads = [
            {"title": f"thread-{index}", "summary": "summary", "comments": []}
            for index in range(35)
        ]

        with tempfile.TemporaryDirectory() as tmpdir, \
                mock.patch.object(analyze_market, "OUTPUT_DIR", tmpdir), \
                mock.patch.object(
                    analyze_market,
                    "analyze_batch",
                    return_value="completed analysis",
                ) as analyze_batch:
            report_path = analyze_market.generate_report(
                threads,
                model="test-model",
                batch_size=10,
            )

            analyzed_titles = [
                thread["title"]
                for call in analyze_batch.call_args_list
                for thread in call.args[0]
            ]
            self.assertEqual(
                analyzed_titles,
                [thread["title"] for thread in threads],
            )
            self.assertEqual(analyze_batch.call_count, 4)
            self.assertIn(
                "*Source: 35 Reddit Threads*",
                Path(report_path).read_text(encoding="utf-8"),
            )

    def test_failed_batch_does_not_publish_report(self):
        threads = [{"title": "thread", "summary": "summary", "comments": []}]

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "reports"
            with mock.patch.object(analyze_market, "OUTPUT_DIR", str(output_dir)), \
                    mock.patch.object(
                        analyze_market,
                        "analyze_batch",
                        side_effect=RuntimeError("Ollama timed out"),
                    ):
                with self.assertRaisesRegex(RuntimeError, "Ollama timed out"):
                    analyze_market.generate_report(
                        threads,
                        model="test-model",
                        batch_size=10,
                    )

            self.assertFalse(output_dir.exists())

    def test_analyze_batch_rejects_empty_llm_response(self):
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {"response": ""}

        with mock.patch.object(
            analyze_market.requests,
            "post",
            return_value=response,
        ):
            with self.assertRaisesRegex(RuntimeError, "empty response"):
                analyze_market.analyze_batch(
                    [{"title": "thread", "summary": "summary", "comments": []}],
                    model="test-model",
                )


if __name__ == "__main__":
    unittest.main()
