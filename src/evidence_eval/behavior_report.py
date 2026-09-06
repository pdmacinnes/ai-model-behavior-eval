from __future__ import annotations

from itertools import combinations
import json
from pathlib import Path
import re
from typing import Any

from .analysis import analyze_trace
from .public import validate_public_batch_manifest


BEHAVIOR_REPORT_SCHEMA = "evidence-bounded-debugging-behavior-report-v1"
_BEHAVIOR_FIELDS = (
    "action_sequence",
    "target_sequence",
    "action_counts",
    "first_action",
    "first_target",
    "actions_before_first_edit",
    "first_edit_target",
    "repair_attempted",
    "edit_count",
    "termination_reason",
    "budget_exhausted",
    "checkpoint_count",
    "leading_hypotheses",
    "confidence_sequence",
    "rejected_action_count",
    "remaining_cost",
)
_LOCAL_PATH_PATTERN = re.compile(r"(?:[A-Za-z]:\\[^\s\"']+|/(?:Users|home|workspace)/[^\s\"']+)")
_SECRET_PATTERN = re.compile(r"\b(?:sk|rk|sess)-[A-Za-z0-9_-]{8,}\b|\bBearer\s+[A-Za-z0-9._-]{8,}", re.IGNORECASE)
_RUN_ID_VARIANT_PATTERN = re.compile(r"-v(?P<variant>\d+)-r(?P<repetition>\d+)$")


class BehaviorReportError(ValueError):
    """Raised when a report source is incomplete or unsafe to process."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BehaviorReportError(f"could not read JSON artifact: {path.name}") from exc


def _safe_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return _SECRET_PATTERN.sub("[credential redacted]", _LOCAL_PATH_PATTERN.sub("[path redacted]", value))


def _safe_value(value: Any) -> Any:
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {_safe_text(str(key)): _safe_value(child) for key, child in value.items()}
    return value


def _empty_behavior() -> dict[str, Any]:
    return {
        "action_sequence": [],
        "target_sequence": [],
        "action_counts": {},
        "first_action": None,
        "first_target": None,
        "actions_before_first_edit": None,
        "first_edit_target": None,
        "repair_attempted": None,
        "edit_count": None,
        "termination_reason": None,
        "budget_exhausted": None,
        "checkpoint_count": None,
        "leading_hypotheses": [],
        "confidence_sequence": [],
        "rejected_action_count": None,
        "remaining_cost": None,
    }


def _project_behavior(value: dict[str, Any]) -> dict[str, Any]:
    projected = _empty_behavior()
    for field in _BEHAVIOR_FIELDS:
        if field in value:
            projected[field] = _safe_value(value[field])
    return projected


def _behavior_from_run(run_dir: Path) -> dict[str, Any]:
    trace_path = run_dir / "event_trace.json"
    if trace_path.is_file():
        trace = _read_json(trace_path)
        if not isinstance(trace, dict):
            raise BehaviorReportError("event trace must be an object")
        if not trace.get("events") and isinstance(trace.get("trace"), dict):
            trace = trace["trace"]
        return _project_behavior(analyze_trace(trace))

    annotations_path = run_dir / "behavioral_annotations.json"
    if annotations_path.is_file():
        annotations = _read_json(annotations_path)
        if not isinstance(annotations, dict):
            raise BehaviorReportError("behavioral annotations must be an object")
        return _project_behavior(annotations)

    return _empty_behavior()


def _condition_metadata(condition_id: Any, condition: Any) -> dict[str, Any]:
    if not isinstance(condition, dict):
        condition = {}
    metadata: dict[str, Any] = {"condition_id": condition_id}
    for field in ("provider", "model_id", "adapter_id", "reasoning_effort", "network_required"):
        if field in condition:
            metadata[field] = _safe_value(condition[field])
    return metadata


def _merge_trial_metadata(manifest: dict[str, Any], batch_id: str) -> dict[str, dict[str, Any]]:
    conditions = {
        item.get("condition_id"): item
        for item in manifest.get("conditions", [])
        if isinstance(item, dict) and isinstance(item.get("condition_id"), str)
    }
    metadata: dict[str, dict[str, Any]] = {}
    for source_name in ("planned_trials", "results"):
        entries = manifest.get(source_name, [])
        if not isinstance(entries, list):
            raise BehaviorReportError(f"batch {batch_id} has malformed {source_name}")
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("run_id"), str):
                raise BehaviorReportError(f"batch {batch_id} has an invalid {source_name} entry")
            run_id = entry["run_id"]
            current = metadata.setdefault(run_id, {"batch_id": batch_id})
            current.update({key: _safe_value(entry[key]) for key in entry if key != "run_id"})
            condition_id = current.get("condition_id")
            if condition_id in conditions:
                current["condition"] = _condition_metadata(condition_id, conditions[condition_id])
    return metadata


def _load_batch_metadata(source_root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    batches_root = source_root / "batches"
    if not batches_root.exists():
        return {}, []
    if not batches_root.is_dir():
        raise BehaviorReportError("source batches entry is not a directory")

    by_run: dict[str, dict[str, Any]] = {}
    batch_ids: list[str] = []
    for batch_dir in sorted(path for path in batches_root.iterdir() if path.is_dir()):
        manifest_path = batch_dir / "manifest.json"
        if not manifest_path.is_file():
            continue
        manifest = _read_json(manifest_path)
        if not isinstance(manifest, dict):
            raise BehaviorReportError(f"batch {batch_dir.name} manifest must be an object")
        try:
            validate_public_batch_manifest(manifest)
        except ValueError as exc:
            raise BehaviorReportError(f"batch {batch_dir.name} manifest is not publishable") from exc
        batch_id = manifest.get("batch_id", batch_dir.name)
        if not isinstance(batch_id, str):
            raise BehaviorReportError(f"batch {batch_dir.name} has an invalid batch id")
        batch_ids.append(batch_id)
        for run_id, metadata in _merge_trial_metadata(manifest, batch_id).items():
            if run_id in by_run and by_run[run_id].get("batch_id") != batch_id:
                raise BehaviorReportError(f"run id appears in multiple batches: {run_id}")
            by_run[run_id] = metadata
    return by_run, sorted(set(batch_ids))


def _inferred_trial_fields(run_id: str) -> dict[str, Any]:
    match = _RUN_ID_VARIANT_PATTERN.search(run_id)
    if not match:
        return {}
    return {
        "variant_slot": int(match.group("variant")),
        "repetition": int(match.group("repetition")),
    }


def _run_entry(run_dir: Path, batch_metadata: dict[str, dict[str, Any]]) -> dict[str, Any]:
    run_path = run_dir / "run.json"
    if not run_path.is_file():
        raise FileNotFoundError
    raw_run = _read_json(run_path)
    if not isinstance(raw_run, dict) or not isinstance(raw_run.get("run_id"), str):
        raise BehaviorReportError("run.json must contain a string run_id")
    run_id = raw_run["run_id"]
    trial = dict(batch_metadata.get(run_id, {}))
    trial.update({key: raw_run[key] for key in ("family_id", "execution_status", "infrastructure_censored") if key in raw_run})
    trial.update({key: value for key, value in _inferred_trial_fields(run_id).items() if key not in trial})

    raw_condition = raw_run.get("condition") if isinstance(raw_run.get("condition"), dict) else {}
    condition_id = trial.get("condition_id", raw_run.get("registration_id"))
    condition = trial.get("condition")
    if not isinstance(condition, dict):
        condition = _condition_metadata(condition_id, raw_condition)
    verifier = raw_run.get("verifier_result")
    if not isinstance(verifier, dict):
        verifier = {}

    entry: dict[str, Any] = {
        "run_id": run_id,
        "batch_id": trial.get("batch_id"),
        "condition": condition,
        "family_id": trial.get("family_id"),
        "repetition": trial.get("repetition"),
        "variant_slot": trial.get("variant_slot", "redacted"),
        "execution_status": trial.get("execution_status", raw_run.get("execution_status")),
        "infrastructure_censored": trial.get("infrastructure_censored", raw_run.get("infrastructure_censored", False)),
        "verifier_status": verifier.get("status", trial.get("verifier_status")),
        "verifier_passed": verifier.get("passed", trial.get("verifier_passed")),
        "behavior": _behavior_from_run(run_dir),
    }
    return _safe_value(entry)


def _comparison_key(run: dict[str, Any]) -> tuple[Any, ...]:
    condition = run.get("condition")
    condition_id = condition.get("condition_id") if isinstance(condition, dict) else None
    return run.get("batch_id"), condition_id, run.get("family_id"), run.get("repetition")


def _build_comparisons(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for run in runs:
        if isinstance(run.get("variant_slot"), int):
            groups.setdefault(_comparison_key(run), []).append(run)

    comparisons: list[dict[str, Any]] = []
    for key, group in sorted(groups.items(), key=lambda item: tuple(str(part) for part in item[0])):
        group.sort(key=lambda run: (run["variant_slot"], run["run_id"]))
        for first, second in combinations(group, 2):
            if first["variant_slot"] == second["variant_slot"]:
                continue
            first_behavior = first["behavior"]
            second_behavior = second["behavior"]
            changed = [field for field in _BEHAVIOR_FIELDS if first_behavior.get(field) != second_behavior.get(field)]
            comparisons.append(
                {
                    "condition_id": key[1],
                    "family_id": key[2],
                    "repetition": key[3],
                    "first_variant_slot": first["variant_slot"],
                    "second_variant_slot": second["variant_slot"],
                    "batch_id": key[0],
                    "changed_behavior_fields": changed,
                    "behavior_changed": bool(changed),
                    "comparison_is_causal_only_if_pre_registered": True,
                }
            )
    return comparisons


def build_behavior_report(source_root: Path, *, source_kind: str) -> dict[str, Any]:
    source_root = source_root.resolve()
    runs_root = source_root / "runs"
    if not runs_root.exists() or not runs_root.is_dir():
        raise BehaviorReportError("source must contain a runs directory")
    batch_metadata, batch_ids = _load_batch_metadata(source_root)
    runs: list[dict[str, Any]] = []
    skipped: list[str] = []
    seen_run_ids: set[str] = set()
    for run_dir in sorted(path for path in runs_root.iterdir() if path.is_dir()):
        try:
            entry = _run_entry(run_dir, batch_metadata)
        except FileNotFoundError:
            skipped.append(run_dir.name)
            continue
        if entry["run_id"] in seen_run_ids:
            raise BehaviorReportError(f"duplicate run id: {entry['run_id']}")
        seen_run_ids.add(entry["run_id"])
        runs.append(entry)

    runs.sort(key=lambda run: run["run_id"])
    report = {
        "schema": BEHAVIOR_REPORT_SCHEMA,
        "report_version": 1,
        "source": {
            "source_kind": source_kind,
            "batch_ids": batch_ids,
            "run_count": len(runs),
            "skipped_run_directories": sorted(skipped),
        },
        "runs": runs,
        "comparisons": _build_comparisons(runs),
        "limitations": [
            "This report describes observable behavior and does not rank models or compute a composite score.",
            "Paired differences are causal only when the comparison was pre-registered.",
            "Verifier outcomes are reported separately from evidence selection and diagnosis behavior.",
        ],
    }
    try:
        validate_public_batch_manifest(report)
    except ValueError as exc:
        raise BehaviorReportError("report contains a non-public field") from exc
    return report
