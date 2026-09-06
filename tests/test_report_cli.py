from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _load_builder():
    path = ROOT / "scripts" / "build_behavioral_report.py"
    spec = importlib.util.spec_from_file_location("behavioral_report_builder", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load behavioral report builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReportCliTests(unittest.TestCase):
    def test_default_output_is_compact_and_verbose_is_explicit(self):
        builder = _load_builder()
        report = {
            "runs": [{"infrastructure_censored": True}],
            "profiles": [{}],
            "comparisons": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            argv = [
                "build_behavioral_report.py",
                "--public-root",
                directory,
                "--output",
                str(output),
            ]
            compact_stdout = io.StringIO()
            with patch.object(builder, "build_behavior_report", return_value=report), patch.object(sys, "argv", argv):
                with redirect_stdout(compact_stdout):
                    self.assertEqual(builder.main(), 0)
            self.assertIn("source_kind=public_release", compact_stdout.getvalue())
            self.assertIn("runs=1", compact_stdout.getvalue())
            self.assertIn("censored=1", compact_stdout.getvalue())
            self.assertNotIn('"runs"', compact_stdout.getvalue())
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), report)

            verbose_argv = argv + ["--verbose"]
            verbose_stdout = io.StringIO()
            with patch.object(builder, "build_behavior_report", return_value=report), patch.object(sys, "argv", verbose_argv):
                with redirect_stdout(verbose_stdout):
                    self.assertEqual(builder.main(), 0)
            self.assertIn('"runs"', verbose_stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
