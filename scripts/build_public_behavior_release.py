from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evidence_eval.public import PUBLIC_EXCLUDED_ARTIFACTS, sanitize_public_artifact, sanitize_public_case_family


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build(cases_root: Path, output_root: Path, artifacts_root: Path | None = None) -> dict[str, Any]:
    case_output = output_root / "cases"
    case_output.mkdir(parents=True, exist_ok=True)
    case_count = 0
    for path in sorted(cases_root.glob("*/family.json")):
        sanitized = sanitize_public_case_family(_read_json(path))
        destination = case_output / path.parent.name / "family.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(sanitized, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        case_count += 1

    run_count = 0
    batch_count = 0
    if artifacts_root is not None and artifacts_root.exists():
        for batch_dir in sorted(path for path in (artifacts_root / "batches").glob("*") if path.is_dir()):
            source = batch_dir / "manifest.json"
            if not source.is_file():
                continue
            sanitized = sanitize_public_artifact("manifest.json", _read_json(source))
            destination = output_root / "batches" / batch_dir.name / "manifest.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(sanitized, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
            batch_count += 1
        for run_dir in sorted(path for path in artifacts_root.glob("runs/*") if path.is_dir()):
            for source in sorted(run_dir.glob("*.json")):
                if source.name in PUBLIC_EXCLUDED_ARTIFACTS:
                    continue
                sanitized = sanitize_public_artifact(source.name, _read_json(source))
                destination = output_root / "runs" / run_dir.name / source.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(json.dumps(sanitized, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
            run_count += 1

    manifest = {
        "schema": "evidence-bounded-debugging-public-release-v1",
        "sanitizer_version": "2",
        "case_count": case_count,
        "run_count": run_count,
        "batch_count": batch_count,
        "excluded_artifacts": list(PUBLIC_EXCLUDED_ARTIFACTS),
        "answer_key_fields_removed": ["hidden_cause", "verifier", "calibration", "reveals", "revealed_factors"],
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a sanitized public behavior-evaluation release.")
    parser.add_argument("--cases-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--artifacts-root", type=Path)
    args = parser.parse_args()
    manifest = build(args.cases_root.resolve(), args.output_root.resolve(), args.artifacts_root.resolve() if args.artifacts_root else None)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
