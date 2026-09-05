from __future__ import annotations

import json
import sys
from pathlib import Path

from evidence_eval.calibration import calibrate_case_family
from evidence_eval.case_validation import validate_case_family
from evidence_eval.schema import load_case_family


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    reports = []
    for path in sorted((root / "behavior_cases").glob("*/family.json")):
        family = load_case_family(path)
        report = validate_case_family(family)
        calibration = calibrate_case_family(family)
        report["calibration"] = calibration
        report["valid"] = report["valid"] and calibration["valid"]
        report["source_path"] = str(path.relative_to(root))
        reports.append(report)
    if not reports:
        print("no behavior cases found", file=sys.stderr)
        return 1
    print(json.dumps(reports, indent=2, sort_keys=True))
    return 0 if all(report["valid"] for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
