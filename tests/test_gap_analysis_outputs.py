import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import networkx as nx

import gap_analysis


class GapAnalysisOutputTests(unittest.TestCase):
    def test_visualization_never_overwrites_non_json_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.jsonl"
            output_path = Path(tmpdir) / "gaps.png"
            input_path.write_text('{"title": "sample"}\n', encoding="utf-8")
            args = SimpleNamespace(
                input=str(input_path),
                output=str(output_path),
                viz=True,
                top=20,
                min_degree=2,
            )

            def fake_visualize(graph, gaps, path):
                Path(path).write_bytes(b"PNG")

            with mock.patch.object(gap_analysis, "parse_args", return_value=args), \
                    mock.patch.object(gap_analysis, "build_graph", return_value=nx.Graph()), \
                    mock.patch.object(gap_analysis, "find_gaps", return_value=[]), \
                    mock.patch.object(gap_analysis, "find_dense_clusters", return_value={}), \
                    mock.patch.object(gap_analysis, "visualize", side_effect=fake_visualize):
                gap_analysis.main()

            result = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(result["total_posts"], 1)
            self.assertEqual(output_path.with_name("gaps_viz.png").read_bytes(), b"PNG")

    def test_output_cannot_overwrite_input(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "input.jsonl"
            original = '{"title": "must survive"}\n'
            input_path.write_text(original, encoding="utf-8")
            args = SimpleNamespace(
                input=str(input_path),
                output=str(input_path),
                viz=False,
                top=20,
                min_degree=2,
            )

            with mock.patch.object(gap_analysis, "parse_args", return_value=args), \
                    self.assertRaisesRegex(SystemExit, "Refusing to overwrite"):
                gap_analysis.main()

            self.assertEqual(input_path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
