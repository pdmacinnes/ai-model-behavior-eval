from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evidence_eval.model_matrix import build_registration_payload, load_model_matrix


PRIMARY_BATCH_IDS = (
    "model-matrix-openai-full-v2",
    "model-matrix-google-full-v2",
    "model-matrix-xai-full-v2",
)
RECOVERY_BOUNDS = {
    "max_rounds": 48,
    "max_conversation_messages": 96,
    "max_conversation_chars": 384_000,
}
RECOVERY_TRIAL_TIMEOUT_SECONDS = 360
RECOVERY_WORKER_TIMEOUT_SECONDS = 330
REPAIR_BUDGET_OVERRIDES = {
    "dashboard-filter-refresh": 14,
    "pagination-offset": 8,
    "session-refresh-role": 8,
}


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected an object: {path}")
    return value


def _write_registration(path: Path, payload: dict) -> Path:
    if path.exists():
        raise ValueError(f"refusing to overwrite generated registration: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return path


def _recovery_payloads(matrix, artifacts_root: Path, project_root: Path, output_dir: Path) -> list[Path]:
    censored: list[tuple[str, dict, dict]] = []
    for batch_id in PRIMARY_BATCH_IDS:
        manifest_path = artifacts_root / "batches" / batch_id / "manifest.json"
        manifest = _read_json(manifest_path)
        for result in manifest.get("results", []):
            if not isinstance(result, dict) or result.get("infrastructure_censored") is not True:
                continue
            run_id = result.get("run_id")
            if not isinstance(run_id, str):
                raise ValueError(f"censored result lacks run id: {manifest_path}")
            run = _read_json(artifacts_root / "runs" / run_id / "run.json")
            censored.append((batch_id, result, run))
    if len(censored) != 8:
        raise ValueError(f"expected exactly 8 censored primary trials, found {len(censored)}")

    condition_by_id = {condition.condition_id: condition for condition in matrix.active_conditions}
    paths: list[Path] = []
    for source_batch_id, result, run in censored:
        condition_id = result.get("condition_id")
        family_id = result.get("family_id")
        repetition = result.get("repetition")
        variant_id = run.get("variant_id")
        if not all(isinstance(value, str) for value in (condition_id, family_id, variant_id)) or not isinstance(repetition, int):
            raise ValueError(f"censored trial has incomplete recovery metadata: {source_batch_id}")
        condition = condition_by_id.get(condition_id)
        if condition is None:
            raise ValueError(f"censored trial uses an inactive condition: {condition_id}")
        payload = build_registration_payload(
            (condition,),
            provider=condition.provider,
            mode="full",
            project_root=project_root,
            python_executable=Path(sys.executable),
            batch_label="recovery-v1",
            trial_timeout_seconds=RECOVERY_TRIAL_TIMEOUT_SECONDS,
            worker_timeout_seconds=RECOVERY_WORKER_TIMEOUT_SECONDS,
            worker_bounds=RECOVERY_BOUNDS,
        )
        payload["batch_id"] = f"recovery-{condition.provider}-{condition_id}-{family_id}-{variant_id}-r{repetition}"
        payload["family_ids"] = [family_id]
        payload["variant_ids"] = {family_id: [variant_id]}
        payload["repetitions"] = 1
        path = output_dir / f"{payload['batch_id']}.json"
        paths.append(_write_registration(path, payload))
    return paths


def _repair_payload(
    matrix,
    *,
    provider: str,
    condition_ids: set[str],
    project_root: Path,
    output_dir: Path,
    batch_id: str,
) -> Path:
    conditions = tuple(
        condition
        for condition in matrix.conditions_for_provider(provider)
        if condition.condition_id in condition_ids
    )
    if {condition.condition_id for condition in conditions} != condition_ids:
        raise ValueError(f"repair audit condition selection is incomplete for {provider}")
    payload = build_registration_payload(
        conditions,
        provider=provider,
        mode="full",
        project_root=project_root,
        python_executable=Path(sys.executable),
        batch_label="repair-v1",
        trial_timeout_seconds=RECOVERY_TRIAL_TIMEOUT_SECONDS,
        worker_timeout_seconds=RECOVERY_WORKER_TIMEOUT_SECONDS,
        worker_bounds=RECOVERY_BOUNDS,
        budget_overrides=REPAIR_BUDGET_OVERRIDES,
    )
    payload["batch_id"] = batch_id
    return _write_registration(output_dir / f"{batch_id}.json", payload)


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Create audited recovery and repair-completion registrations.")
    parser.add_argument("--matrix", type=Path, default=project_root / "configs" / "model_matrix.json")
    parser.add_argument("--artifacts-root", type=Path, default=project_root / "results" / "model-matrix")
    parser.add_argument("--output-dir", type=Path, default=project_root / "results" / "model-matrix" / "audit-registrations-v2")
    parser.add_argument("--audit-label", default="v1")
    args = parser.parse_args()

    matrix = load_model_matrix(args.matrix.resolve())
    output_dir = args.output_dir.resolve()
    artifacts_root = args.artifacts_root.resolve()
    recovery_paths = _recovery_payloads(matrix, artifacts_root, project_root, output_dir)
    repair_paths = [
        _repair_payload(
            matrix,
            provider="anthropic",
            condition_ids={"anthropic-claude-opus-5", "anthropic-claude-sonnet-5"},
            project_root=project_root,
            output_dir=output_dir,
            batch_id=f"repair-anthropic-{args.audit_label}",
        ),
        _repair_payload(
            matrix,
            provider="meta",
            condition_ids={"meta-muse-spark-1-3"},
            project_root=project_root,
            output_dir=output_dir,
            batch_id=f"repair-meta-{args.audit_label}",
        ),
    ]
    print(json.dumps({"recovery": [str(path) for path in recovery_paths], "repair": [str(path) for path in repair_paths]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
