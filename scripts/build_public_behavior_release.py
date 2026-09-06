from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from evidence_eval.public import (
    PUBLIC_EXCLUDED_ARTIFACTS,
    derive_public_pair_id,
    derive_public_run_id,
    sanitize_public_artifact,
    sanitize_public_batch_manifest,
    sanitize_public_case_family,
)


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
        batch_sources = sorted(path for path in (artifacts_root / "batches").glob("*") if path.is_dir())
        trial_mappings: dict[str, dict[str, Any]] = {}
        manifest_values: dict[Path, dict[str, Any]] = {}
        for batch_dir in batch_sources:
            source = batch_dir / "manifest.json"
            if not source.is_file():
                continue
            raw_manifest = _read_json(source)
            if not isinstance(raw_manifest, dict):
                raise ValueError(f"batch manifest must be an object: {source}")
            batch_id = raw_manifest.get("batch_id", batch_dir.name)
            if not isinstance(batch_id, str):
                raise ValueError(f"batch manifest has an invalid batch id: {source}")
            for trial in raw_manifest.get("planned_trials", []):
                if not isinstance(trial, dict) or not isinstance(trial.get("run_id"), str):
                    raise ValueError(f"batch has an invalid planned trial: {source}")
                condition_id = trial.get("condition_id")
                family_id = trial.get("family_id")
                repetition = trial.get("repetition")
                if not isinstance(condition_id, str) or not isinstance(family_id, str) or not isinstance(repetition, int):
                    raise ValueError(f"planned trial lacks pairing metadata: {source}")
                internal_id = trial["run_id"]
                if internal_id in trial_mappings:
                    raise ValueError(f"duplicate internal run id across batches: {internal_id}")
                trial_mappings[internal_id] = {
                    "public_run_id": derive_public_run_id(batch_id, internal_id),
                    "pair_id": derive_public_pair_id(batch_id, condition_id, family_id, repetition),
                    "batch_id": batch_id,
                    "repetition": repetition,
                }
            manifest_values[batch_dir] = raw_manifest

        for batch_dir in batch_sources:
            raw_manifest = manifest_values.get(batch_dir)
            if raw_manifest is None:
                continue
            batch_id = raw_manifest.get("batch_id", batch_dir.name)
            sanitized = sanitize_public_batch_manifest(raw_manifest, trial_mappings)
            destination = output_root / "batches" / batch_dir.name / "manifest.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(sanitized, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
            registration = _public_registration_projection(sanitized, batch_id)
            registration_path = output_root / "batches" / batch_dir.name / "registration.json"
            registration_path.write_text(json.dumps(registration, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
            batch_count += 1
            registration_count += 1
        for run_dir in sorted(path for path in artifacts_root.glob("runs/*") if path.is_dir()):
            raw_run_path = run_dir / "run.json"
            if not raw_run_path.is_file():
                raise ValueError(f"run directory lacks run.json: {run_dir}")
            raw_run = _read_json(raw_run_path)
            if not isinstance(raw_run, dict) or not isinstance(raw_run.get("run_id"), str):
                raise ValueError(f"run.json lacks a string run_id: {raw_run_path}")
            internal_run_id = raw_run["run_id"]
            info = trial_mappings.get(internal_run_id)
            if info is None:
                raise ValueError(f"run is not registered in a batch manifest: {internal_run_id}")
            destination_run = output_root / "runs" / info["public_run_id"]
            for source in sorted(run_dir.glob("*.json")):
                if source.name in PUBLIC_EXCLUDED_ARTIFACTS:
                    continue
                sanitized = sanitize_public_artifact(source.name, _read_json(source))
                if source.name == "run.json" and isinstance(sanitized, dict):
                    sanitized["run_id"] = info["public_run_id"]
                    sanitized["pair_id"] = info["pair_id"]
                    sanitized["repetition"] = info["repetition"]
                    sanitized["batch_id"] = info["batch_id"]
                destination = destination_run / source.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(json.dumps(sanitized, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
            run_count += 1

    manifest = {
        "schema": "evidence-bounded-debugging-public-release-v2",
        "sanitizer_version": "3",
        "case_count": case_count,
        "run_count": run_count,
        "batch_count": batch_count,
        "registration_count": registration_count,
        "excluded_artifacts": list(PUBLIC_EXCLUDED_ARTIFACTS),
        "answer_key_fields_removed": [
            "hidden_cause",
            "verifier",
            "calibration",
            "reveals",
            "revealed_factors",
            "variant_id",
            "variant_slot",
            "fixture_files",
            "observation_content",
            "cause_named_hypotheses",
        ],
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

Raw adapter results and final provider responses are intentionally excluded. Fixture source bodies, cause-discriminating observation prose, predefined cause-named hypotheses, hidden causes, verifier declarations, calibration data, variant identifiers, variant slots, credentials, machine-local paths, and commands are not part of the public release. Model-authored checkpoint text is retained as behavioral evidence and may still paraphrase a cause.

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
