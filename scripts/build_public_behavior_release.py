from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evidence_eval.public import PUBLIC_EXCLUDED_ARTIFACTS, sanitize_public_artifact, sanitize_public_case_family


PUBLIC_REGISTRATION_SCHEMA = "evidence-bounded-debugging-public-registration-v1"


def _public_registration_projection(manifest: dict[str, Any], batch_id: str) -> dict[str, Any]:
    conditions = []
    for condition in manifest.get("conditions", []):
        if not isinstance(condition, dict):
            continue
        conditions.append(
            {
                key: condition.get(key)
                for key in (
                    "condition_id",
                    "provider",
                    "model_id",
                    "adapter_id",
                    "reasoning_effort",
                    "network_required",
                )
                if key in condition
            }
        )
    planned_trials = manifest.get("planned_trials", [])
    family_ids = sorted({trial.get("family_id") for trial in planned_trials if isinstance(trial, dict) and isinstance(trial.get("family_id"), str)})
    repetitions = sorted({trial.get("repetition") for trial in planned_trials if isinstance(trial, dict) and isinstance(trial.get("repetition"), int)})
    return {
        "schema": PUBLIC_REGISTRATION_SCHEMA,
        "batch_id": batch_id,
        "registration_hash": manifest.get("registration_hash"),
        "case_set_hash": manifest.get("case_set_hash"),
        "harness_version": manifest.get("harness_version"),
        "family_ids": family_ids,
        "repetitions": repetitions,
        "planned_trial_count": len(planned_trials) if isinstance(planned_trials, list) else 0,
        "conditions": sorted(conditions, key=lambda item: str(item.get("condition_id", ""))),
    }


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


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
    registration_count = 0
    if artifacts_root is not None and artifacts_root.exists():
        for batch_dir in sorted(path for path in (artifacts_root / "batches").glob("*") if path.is_dir()):
            source = batch_dir / "manifest.json"
            if not source.is_file():
                continue
            sanitized = sanitize_public_artifact("manifest.json", _read_json(source))
            destination = output_root / "batches" / batch_dir.name / "manifest.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(sanitized, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
            batch_id = sanitized.get("batch_id", batch_dir.name)
            registration = _public_registration_projection(sanitized, batch_id)
            registration_path = output_root / "batches" / batch_dir.name / "registration.json"
            registration_path.write_text(json.dumps(registration, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
            batch_count += 1
            registration_count += 1
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
        "registration_count": registration_count,
        "excluded_artifacts": list(PUBLIC_EXCLUDED_ARTIFACTS),
        "answer_key_fields_removed": ["hidden_cause", "verifier", "calibration", "reveals", "revealed_factors"],
        "entrypoints": {
            "report_builder": "scripts/build_behavioral_report.py",
            "analysis": "src/evidence_eval/analysis.py",
        },
    }
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    _write_text(
        output_root / "README.md",
        """# Evidence-Bounded Debugging Public Release

This directory contains sanitized case definitions, public registration projections, batch manifests, derived run traces, and behavioral annotations for the evidence-bounded debugging study.

Raw adapter results and final provider responses are intentionally excluded. Hidden causes, verifier declarations, calibration data, variant identifiers, credentials, machine-local paths, and commands are not part of the public release.

To rebuild this release from the repository root:

```powershell
$env:PYTHONPATH = 'src'
python scripts/build_public_behavior_release.py --cases-root behavior_cases --artifacts-root results/your-batch --output-root results/public-release
python scripts/build_behavioral_report.py --public-root results/public-release --output results/public-release/behavior-report.json
```

The behavioral report is descriptive. It presents evidence selection, hypotheses, repair attempts, termination, verifier outcomes, paired observations, and recurring structural patterns without a composite score or model ranking.
""",
    )
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
