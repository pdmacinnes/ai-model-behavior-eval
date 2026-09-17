from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from cursor_eval.artifacts import ArtifactExistsError, write_run_artifacts

from .calibration import calibrate_case_family
from .case_validation import validate_case_family
from .execution_policy import (
    ExecutionPolicyError,
    live_environment_names,
    validate_execution_authorization,
)
from .runner import ModelCondition
from .schema import CaseFamily, CaseVariant, load_case_family
from .subprocess_adapter import SubprocessAdapterConfig, SubprocessWorkspaceAdapter
from .workspace_runner import run_workspace_trial


PILOT_REGISTRATION_SCHEMA = "evidence-bounded-debugging-pilot-registration-v1"
PILOT_BATCH_MANIFEST_SCHEMA = "evidence-bounded-debugging-batch-v1"
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


class PilotRegistrationError(ValueError):
    pass


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _source_revision(project_root: Path) -> str:
    """Return a non-sensitive source revision suitable for provenance fields."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable"
    revision = result.stdout.strip()
    return revision if re.fullmatch(r"[0-9a-f]{40}", revision) else "unavailable"


def _safe_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
        raise PilotRegistrationError(f"{label} must contain only letters, numbers, underscore, period, or hyphen")
    return value


def _non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise PilotRegistrationError(f"{label} must be a non-empty string")
    return value


def _positive_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise PilotRegistrationError(f"{label} must be a finite positive number")
    return float(value)


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PilotRegistrationError(f"{label} must be an object")
    return value


def _resolve_path(value: Any, label: str, base: Path) -> Path:
    text = _non_empty_string(value, label)
    path = Path(text)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def _reject_unknown(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise PilotRegistrationError(f"{label} contains unknown fields: {', '.join(unknown)}")


@dataclass(frozen=True)
class PilotCondition:
    condition_id: str
    provider: str
    model_id: str
    adapter_id: str
    command: tuple[str, ...]
    reasoning_effort: str | None
    network_required: bool
    timeout_seconds: float
    transport: str | None = None
    worker_bounds: dict[str, int] | None = None

    def to_payload(self) -> dict[str, Any]:
        value = {
            "condition_id": self.condition_id,
            "provider": self.provider,
            "model_id": self.model_id,
            "adapter_id": self.adapter_id,
            "command": list(self.command),
            "reasoning_effort": self.reasoning_effort,
            "network_required": self.network_required,
            "timeout_seconds": self.timeout_seconds,
        }
        if self.transport is not None:
            value["transport"] = self.transport
        if self.worker_bounds is not None:
            value["worker_bounds"] = dict(self.worker_bounds)
        return value

    def to_public_dict(self) -> dict[str, Any]:
        value = {
            "condition_id": self.condition_id,
            "provider": self.provider,
            "model_id": self.model_id,
            "adapter_id": self.adapter_id,
            "reasoning_effort": self.reasoning_effort,
            "network_required": self.network_required,
            "transport": self.transport,
            "timeout_seconds": self.timeout_seconds,
        }
        if self.worker_bounds is not None:
            value["worker_bounds"] = dict(self.worker_bounds)
        return value

    def model_condition(
        self,
        family: CaseFamily,
        harness_version: str,
        *,
        trial_timeout_seconds: float,
        source_revision: str,
        registration_hash: str,
    ) -> ModelCondition:
        return ModelCondition(
            provider=self.provider,
            model_id=self.model_id,
            adapter_id=self.adapter_id,
            prompt=family.initial_context["prompt"],
            reasoning_effort=self.reasoning_effort,
            harness_version=harness_version,
            transport=self.transport,
            worker_timeout_seconds=self.timeout_seconds,
            trial_timeout_seconds=trial_timeout_seconds,
            source_revision=source_revision,
            registration_hash=registration_hash,
            worker_bounds=self.worker_bounds,
        )


@dataclass(frozen=True)
class PilotRegistration:
    batch_id: str
    harness_version: str
    case_root: Path
    family_ids: tuple[str, ...]
    variant_ids: dict[str, tuple[str, ...]]
    repetitions: int
    trial_timeout_seconds: float
    artifacts_root: Path
    workspace_parent: Path
    conditions: tuple[PilotCondition, ...]
    budget_overrides: dict[str, int] = field(default_factory=dict)
    registration_hash: str = ""
    source_path: Path | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "schema": PILOT_REGISTRATION_SCHEMA,
            "batch_id": self.batch_id,
            "harness_version": self.harness_version,
            "case_root": str(self.case_root),
            "family_ids": list(self.family_ids),
            "variant_ids": {key: list(value) for key, value in sorted(self.variant_ids.items())},
            "repetitions": self.repetitions,
            "trial_timeout_seconds": self.trial_timeout_seconds,
            "artifacts_root": str(self.artifacts_root),
            "workspace_parent": str(self.workspace_parent),
            "conditions": [condition.to_payload() for condition in self.conditions],
            "budget_overrides": dict(sorted(self.budget_overrides.items())),
        }

    def digest(self) -> str:
        return self.registration_hash or _canonical_hash(self.payload())


@dataclass(frozen=True)
class PlannedTrial:
    run_id: str
    condition: PilotCondition
    family_id: str
    variant_id: str
    variant_slot: int
    repetition: int

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "condition_id": self.condition.condition_id,
            "provider": self.condition.provider,
            "model_id": self.condition.model_id,
            "adapter_id": self.condition.adapter_id,
            "transport": self.condition.transport,
            "family_id": self.family_id,
            "variant_slot": self.variant_slot,
            "repetition": self.repetition,
        }


def _parse_condition(raw: Any, index: int) -> PilotCondition:
    value = _require_object(raw, f"conditions[{index}]")
    _reject_unknown(
        value,
        {
            "condition_id",
            "provider",
            "model_id",
            "adapter_id",
            "command",
            "reasoning_effort",
            "network_required",
            "timeout_seconds",
            "transport",
            "worker_bounds",
        },
        f"conditions[{index}]",
    )
    required = {
        "condition_id",
        "provider",
        "model_id",
        "adapter_id",
        "command",
        "reasoning_effort",
        "network_required",
        "timeout_seconds",
    }
    missing = sorted(required - set(value))
    if missing:
        raise PilotRegistrationError(f"conditions[{index}] is missing fields: {', '.join(missing)}")
    command = value["command"]
    if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
        raise PilotRegistrationError(f"conditions[{index}].command must be a non-empty list of strings")
    reasoning_effort = value["reasoning_effort"]
    if reasoning_effort is not None and (not isinstance(reasoning_effort, str) or not reasoning_effort):
        raise PilotRegistrationError(f"conditions[{index}].reasoning_effort must be a string or null")
    if type(value["network_required"]) is not bool:
        raise PilotRegistrationError(f"conditions[{index}].network_required must be a boolean")
    transport = value.get("transport")
    if transport is not None:
        transport = _safe_identifier(transport, f"conditions[{index}].transport")
    worker_bounds = value.get("worker_bounds")
    if worker_bounds is not None:
        worker_bounds = _require_object(worker_bounds, f"conditions[{index}].worker_bounds")
        _reject_unknown(
            worker_bounds,
            {"max_rounds", "max_conversation_messages", "max_conversation_chars"},
            f"conditions[{index}].worker_bounds",
        )
        if set(worker_bounds) != {"max_rounds", "max_conversation_messages", "max_conversation_chars"}:
            raise PilotRegistrationError(f"conditions[{index}].worker_bounds must specify all worker bounds")
        parsed_bounds: dict[str, int] = {}
        for key, item in worker_bounds.items():
            if type(item) is not int or item <= 0:
                raise PilotRegistrationError(f"conditions[{index}].worker_bounds.{key} must be a positive integer")
            parsed_bounds[key] = item
        worker_bounds = parsed_bounds
    return PilotCondition(
        condition_id=_safe_identifier(value["condition_id"], f"conditions[{index}].condition_id"),
        provider=_non_empty_string(value["provider"], f"conditions[{index}].provider"),
        model_id=_non_empty_string(value["model_id"], f"conditions[{index}].model_id"),
        adapter_id=_safe_identifier(value["adapter_id"], f"conditions[{index}].adapter_id"),
        command=tuple(command),
        reasoning_effort=reasoning_effort,
        network_required=value["network_required"],
        timeout_seconds=_positive_number(value["timeout_seconds"], f"conditions[{index}].timeout_seconds"),
        transport=transport,
        worker_bounds=worker_bounds,
    )


def _parse_budget_overrides(value: Any) -> dict[str, int]:
    if value is None:
        return {}
    raw = _require_object(value, "budget_overrides")
    parsed: dict[str, int] = {}
    for family_id, budget in raw.items():
        family_key = _safe_identifier(family_id, "budget_overrides family")
        if type(budget) is not int or budget <= 0:
            raise PilotRegistrationError(f"budget_overrides[{family_id!r}] must be a positive integer")
        parsed[family_key] = budget
    return parsed


def _parse_variant_ids(value: Any) -> dict[str, tuple[str, ...]]:
    if value is None:
        return {}
    raw = _require_object(value, "variant_ids")
    parsed: dict[str, tuple[str, ...]] = {}
    for family_id, variants in raw.items():
        family_key = _safe_identifier(family_id, "variant_ids family")
        if not isinstance(variants, list) or not variants or any(not isinstance(item, str) or not item for item in variants):
            raise PilotRegistrationError(f"variant_ids[{family_id!r}] must be a non-empty list of strings")
        if len(set(variants)) != len(variants):
            raise PilotRegistrationError(f"variant_ids[{family_id!r}] must not contain duplicates")
        parsed[family_key] = tuple(variants)
    return parsed


def load_pilot_registration(path: Path) -> PilotRegistration:
    source_path = path.resolve()
    try:
        raw = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PilotRegistrationError(f"could not read pilot registration: {type(exc).__name__}") from exc
    value = _require_object(raw, "pilot registration")
    _reject_unknown(
        value,
        {
            "schema",
            "batch_id",
            "harness_version",
            "case_root",
            "family_ids",
            "variant_ids",
            "repetitions",
            "trial_timeout_seconds",
            "artifacts_root",
            "workspace_parent",
            "conditions",
            "budget_overrides",
        },
        "pilot registration",
    )
    required = {
        "schema",
        "batch_id",
        "harness_version",
        "case_root",
        "family_ids",
        "repetitions",
        "trial_timeout_seconds",
        "artifacts_root",
        "workspace_parent",
        "conditions",
    }
    missing = sorted(required - set(value))
    if missing:
        raise PilotRegistrationError(f"pilot registration is missing fields: {', '.join(missing)}")
    if value["schema"] != PILOT_REGISTRATION_SCHEMA:
        raise PilotRegistrationError(f"unsupported pilot registration schema: {value['schema']!r}")
    family_ids = value["family_ids"]
    if not isinstance(family_ids, list) or not family_ids or any(not isinstance(item, str) or not item for item in family_ids):
        raise PilotRegistrationError("family_ids must be a non-empty list of strings")
    if len(set(family_ids)) != len(family_ids):
        raise PilotRegistrationError("family_ids must not contain duplicates")
    if type(value["repetitions"]) is not int or value["repetitions"] <= 0:
        raise PilotRegistrationError("repetitions must be a positive integer")
    conditions = value["conditions"]
    if not isinstance(conditions, list) or not conditions:
        raise PilotRegistrationError("conditions must be a non-empty list")
    parsed_conditions = tuple(_parse_condition(item, index) for index, item in enumerate(conditions))
    condition_ids = [item.condition_id for item in parsed_conditions]
    if len(set(condition_ids)) != len(condition_ids):
        raise PilotRegistrationError("condition IDs must be unique")
    base = source_path.parent
    registration = PilotRegistration(
        batch_id=_safe_identifier(value["batch_id"], "batch_id"),
        harness_version=_non_empty_string(value["harness_version"], "harness_version"),
        case_root=_resolve_path(value["case_root"], "case_root", base),
        family_ids=tuple(_safe_identifier(item, "family_id") for item in family_ids),
        variant_ids=_parse_variant_ids(value.get("variant_ids")),
        repetitions=value["repetitions"],
        trial_timeout_seconds=_positive_number(value["trial_timeout_seconds"], "trial_timeout_seconds"),
        artifacts_root=_resolve_path(value["artifacts_root"], "artifacts_root", base),
        workspace_parent=_resolve_path(value["workspace_parent"], "workspace_parent", base),
        conditions=parsed_conditions,
        budget_overrides=_parse_budget_overrides(value.get("budget_overrides")),
        registration_hash=_canonical_hash(value),
        source_path=source_path,
    )
    _validate_registration_shape(registration)
    return registration


def _validate_registration_shape(registration: PilotRegistration) -> None:
    _safe_identifier(registration.batch_id, "batch_id")
    if not registration.family_ids:
        raise PilotRegistrationError("family_ids must not be empty")
    if len(set(registration.family_ids)) != len(registration.family_ids):
        raise PilotRegistrationError("family_ids must not contain duplicates")
    if registration.repetitions <= 0:
        raise PilotRegistrationError("repetitions must be positive")
    _positive_number(registration.trial_timeout_seconds, "trial_timeout_seconds")
    if not registration.conditions:
        raise PilotRegistrationError("conditions must not be empty")
    if len({condition.condition_id for condition in registration.conditions}) != len(registration.conditions):
        raise PilotRegistrationError("condition IDs must be unique")
    for family_id, variant_ids in registration.variant_ids.items():
        if family_id not in registration.family_ids:
            raise PilotRegistrationError(f"variant_ids contains unselected family: {family_id}")
        if not variant_ids or len(set(variant_ids)) != len(variant_ids):
            raise PilotRegistrationError(f"variant_ids[{family_id!r}] must contain unique values")
    for family_id, budget in (registration.budget_overrides or {}).items():
        if family_id not in registration.family_ids:
            raise PilotRegistrationError(f"budget_overrides contains unselected family: {family_id}")
        if type(budget) is not int or budget <= 0:
            raise PilotRegistrationError(f"budget_overrides[{family_id!r}] must be a positive integer")
    for condition in registration.conditions:
        if condition.timeout_seconds >= registration.trial_timeout_seconds:
            raise PilotRegistrationError(
                f"condition {condition.condition_id!r} timeout must be shorter than trial_timeout_seconds"
            )


def _load_families(registration: PilotRegistration) -> dict[str, CaseFamily]:
    _validate_registration_shape(registration)
    families: dict[str, CaseFamily] = {}
    errors: list[str] = []
    if not registration.case_root.is_dir():
        raise PilotRegistrationError(f"case_root does not exist: {registration.case_root}")
    for family_id in registration.family_ids:
        path = registration.case_root / family_id / "family.json"
        try:
            family = load_case_family(path)
            validation = validate_case_family(family)
            calibration = calibrate_case_family(family)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            errors.append(f"{family_id}: {type(exc).__name__}")
            continue
        if not validation["valid"]:
            errors.extend(f"{family_id}: {error}" for error in validation["errors"])
        if not calibration["valid"]:
            errors.extend(f"{family_id}: {error}" for error in calibration["errors"])
        selected = registration.variant_ids.get(family_id, tuple(variant.variant_id for variant in family.variants))
        known = {variant.variant_id for variant in family.variants}
        missing = [variant_id for variant_id in selected if variant_id not in known]
        if missing:
            errors.append(f"{family_id}: unknown selected variants: {', '.join(missing)}")
        if not selected:
            errors.append(f"{family_id}: selected variants must not be empty")
        override = (registration.budget_overrides or {}).get(family_id)
        if override is not None:
            family = replace(family, max_cost=override)
        families[family_id] = family
    if errors:
        raise PilotRegistrationError("pilot preflight failed: " + "; ".join(errors))
    return families


def _selected_variants(registration: PilotRegistration, family: CaseFamily) -> tuple[tuple[int, CaseVariant], ...]:
    selected_ids = registration.variant_ids.get(family.family_id, tuple(variant.variant_id for variant in family.variants))
    selected: list[tuple[int, CaseVariant]] = []
    for slot, variant in enumerate(family.variants, start=1):
        if variant.variant_id in selected_ids:
            selected.append((slot, variant))
    return tuple(selected)


def plan_pilot_trials(registration: PilotRegistration, families: dict[str, CaseFamily]) -> tuple[PlannedTrial, ...]:
    planned: list[PlannedTrial] = []
    seen: set[str] = set()
    for condition in registration.conditions:
        for family_id in registration.family_ids:
            family = families[family_id]
            for variant_slot, variant in _selected_variants(registration, family):
                for repetition in range(1, registration.repetitions + 1):
                    run_id = f"{registration.batch_id}-{condition.condition_id}-{family_id}-v{variant_slot}-r{repetition}"
                    if not _IDENTIFIER_PATTERN.fullmatch(run_id):
                        raise PilotRegistrationError(f"generated run ID is too long or unsafe: {run_id!r}")
                    if run_id in seen:
                        raise PilotRegistrationError(f"generated duplicate run ID: {run_id}")
                    seen.add(run_id)
                    planned.append(
                        PlannedTrial(
                            run_id=run_id,
                            condition=condition,
                            family_id=family_id,
                            variant_id=variant.variant_id,
                            variant_slot=variant_slot,
                            repetition=repetition,
                        )
                    )
    return tuple(planned)


def _batch_failure_record(
    trial: PlannedTrial,
    family: CaseFamily,
    condition: ModelCondition,
    artifacts_root: Path,
    error: Exception,
) -> dict[str, Any]:
    status = "batch_error"
    error_label = type(error).__name__
    verifier = {"verifier_id": f"{family.family_id}:batch-error", "status": "not_run", "passed": False, "error": error_label}
    run_record = {
        "run_id": trial.run_id,
        "registration_id": trial.condition.condition_id,
        "family_id": family.family_id,
        "variant_id": trial.variant_id,
        "case_sha256": family.canonical_sha256,
        "condition": condition.to_dict(),
        "protocol_version": "evidence-workspace-v1",
        "execution_status": status,
        "infrastructure_censored": True,
        "verifier_result": verifier,
        "workspace_cleanup_deferred": False,
        "workspace_cleanup_reason": None,
    }
    artifacts = {
        "run.json": run_record,
        "condition.json": condition.to_dict(),
        "task.json": {},
        "tool_contract.json": {},
        "prompt.txt": condition.prompt,
        "initial_workspace_manifest.json": {},
        "final_workspace_manifest.json": {},
        "mutation_observer.json": {},
        "event_trace.json": {"status": status, "events": []},
        "final_response.txt": "",
        "adapter_result.json": {"status": status, "error": error_label, "metadata": {}},
        "verifier_result.json": verifier,
        "behavioral_annotations.json": {},
    }
    write_run_artifacts(artifacts_root / "runs" / trial.run_id, artifacts)
    return run_record


def _result_summary(trial: PlannedTrial, record: dict[str, Any]) -> dict[str, Any]:
    verifier = record.get("verifier_result", {})
    return {
        "run_id": trial.run_id,
        "condition_id": trial.condition.condition_id,
        "family_id": trial.family_id,
        "variant_slot": trial.variant_slot,
        "repetition": trial.repetition,
        "execution_status": record.get("execution_status"),
        "infrastructure_censored": bool(record.get("infrastructure_censored")),
        "verifier_status": verifier.get("status"),
        "verifier_passed": verifier.get("passed"),
    }


def _aggregates(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for result in results:
        key = (result["condition_id"], result["family_id"])
        group = grouped.setdefault(
            key,
            {
                "condition_id": result["condition_id"],
                "family_id": result["family_id"],
                "trial_count": 0,
                "infrastructure_censored_count": 0,
                "execution_status_counts": {},
                "verifier_status_counts": {},
                "verifier_passed_count": 0,
            },
        )
        group["trial_count"] += 1
        if result["infrastructure_censored"]:
            group["infrastructure_censored_count"] += 1
        execution_status = str(result["execution_status"])
        group["execution_status_counts"][execution_status] = group["execution_status_counts"].get(execution_status, 0) + 1
        verifier_status = str(result["verifier_status"])
        group["verifier_status_counts"][verifier_status] = group["verifier_status_counts"].get(verifier_status, 0) + 1
        if result["verifier_passed"] is True:
            group["verifier_passed_count"] += 1
    return [grouped[key] for key in sorted(grouped)]


def run_pilot_batch(registration: PilotRegistration, *, allow_network: bool = False) -> dict[str, Any]:
    try:
        validate_execution_authorization(registration, allow_network=allow_network)
    except ExecutionPolicyError as exc:
        raise PilotRegistrationError(str(exc)) from exc
    families = _load_families(registration)
    planned = plan_pilot_trials(registration, families)
    source_revision = _source_revision(registration.case_root.parent)
    batch_dir = registration.artifacts_root / "batches" / registration.batch_id
    if batch_dir.exists():
        raise ArtifactExistsError(str(batch_dir))
    for trial in planned:
        if (registration.artifacts_root / "runs" / trial.run_id).exists():
            raise ArtifactExistsError(str(registration.artifacts_root / "runs" / trial.run_id))

    started_at = time.time()
    results: list[dict[str, Any]] = []
    for trial in planned:
        family = families[trial.family_id]
        model_condition = trial.condition.model_condition(
            family,
            registration.harness_version,
            trial_timeout_seconds=registration.trial_timeout_seconds,
            source_revision=source_revision,
            registration_hash=registration.digest(),
        )
        adapter = SubprocessWorkspaceAdapter(
            SubprocessAdapterConfig(
                command=trial.condition.command,
                timeout_seconds=trial.condition.timeout_seconds,
                credential_env_names=live_environment_names(trial.condition),
                network_authorized=trial.condition.network_required,
            )
        )
        try:
            record = run_workspace_trial(
                family,
                family.variant(trial.variant_id),
                model_condition,
                adapter,
                artifacts_root=registration.artifacts_root,
                workspace_parent=registration.workspace_parent,
                run_id=trial.run_id,
                registration_id=trial.condition.condition_id,
                adapter_timeout_seconds=registration.trial_timeout_seconds,
            )
        except ArtifactExistsError:
            raise
        except Exception as exc:
            record = _batch_failure_record(trial, family, model_condition, registration.artifacts_root, exc)
        results.append(_result_summary(trial, record))

    case_set_hash = _canonical_hash({family_id: families[family_id].canonical_sha256 for family_id in registration.family_ids})
    manifest = {
        "schema": PILOT_BATCH_MANIFEST_SCHEMA,
        "batch_id": registration.batch_id,
        "registration_hash": registration.digest(),
        "case_set_hash": case_set_hash,
        "harness_version": registration.harness_version,
        "started_at_utc_epoch": started_at,
        "completed_at_utc_epoch": time.time(),
        "conditions": [condition.to_public_dict() for condition in registration.conditions],
        "source_revision": source_revision,
        "trial_timeout_seconds": registration.trial_timeout_seconds,
        "budget_overrides": dict(sorted(registration.budget_overrides.items())),
        "registration_summary": {
            "family_ids": list(registration.family_ids),
            "repetitions": registration.repetitions,
            "conditions": [condition.to_public_dict() for condition in registration.conditions],
            "trial_timeout_seconds": registration.trial_timeout_seconds,
            "budget_overrides": dict(sorted(registration.budget_overrides.items())),
        },
        "planned_trials": [trial.to_public_dict() for trial in planned],
        "results": results,
        "aggregates": _aggregates(results),
    }
    write_run_artifacts(batch_dir, {"manifest.json": manifest})
    return manifest
