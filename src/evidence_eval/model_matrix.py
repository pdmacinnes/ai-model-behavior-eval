"""Validation and offline generation for the multi-provider model matrix."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MODEL_MATRIX_SCHEMA = "evidence-bounded-debugging-model-matrix-v1"
APPROVED_ADAPTER_ID = "jsonl-provider-worker"
APPROVED_TRANSPORTS = frozenset({"openai-compatible", "openai-responses", "google-gemini"})
SMOKE_FAMILY_IDS = ("dashboard-filter-refresh",)
FULL_FAMILY_IDS = ("dashboard-filter-refresh", "pagination-offset", "session-refresh-role")
SMOKE_REPETITIONS = 1
FULL_REPETITIONS = 2
TRIAL_TIMEOUT_SECONDS = 180
WORKER_TIMEOUT_SECONDS = 150
MATRIX_MAX_ROUNDS = 24
MATRIX_MAX_CONVERSATION_MESSAGES = 48
MATRIX_MAX_CONVERSATION_CHARS = 192_000
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_DISALLOWED_CATALOG_TERMS = ("credential", "secret", "password", "api_key", "token", "endpoint", "path", "command")


class ModelMatrixError(ValueError):
    """Raised when a model catalog or generated registration is invalid."""


@dataclass(frozen=True)
class MatrixCondition:
    condition_id: str
    provider: str
    model_id: str
    transport: str
    reasoning_effort: str | None


@dataclass(frozen=True)
class PendingMatrixCondition:
    condition_id: str
    provider: str
    display_name: str
    reason: str


@dataclass(frozen=True)
class ModelMatrix:
    active_conditions: tuple[MatrixCondition, ...]
    pending_conditions: tuple[PendingMatrixCondition, ...]

    @property
    def providers(self) -> tuple[str, ...]:
        return tuple(sorted({condition.provider for condition in self.active_conditions}))

    def conditions_for_provider(self, provider: str) -> tuple[MatrixCondition, ...]:
        return tuple(condition for condition in self.active_conditions if condition.provider == provider)


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ModelMatrixError(f"{label} must be an object")
    return value


def _reject_unknown(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ModelMatrixError(f"{label} contains unknown fields: {', '.join(unknown)}")


def _safe_identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
        raise ModelMatrixError(f"{label} must be a safe identifier")
    return value


def _non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelMatrixError(f"{label} must be a non-empty string")
    return value


def _validate_catalog_strings(value: dict[str, Any], label: str) -> None:
    for key, item in value.items():
        if any(term in key.lower() for term in _DISALLOWED_CATALOG_TERMS):
            raise ModelMatrixError(f"{label} contains disallowed configuration field: {key}")
        if isinstance(item, str) and any(term in item.lower() for term in _DISALLOWED_CATALOG_TERMS):
            raise ModelMatrixError(f"{label}.{key} contains disallowed configuration text")


def _parse_active_condition(raw: Any, index: int) -> MatrixCondition:
    value = _require_object(raw, f"active_conditions[{index}]")
    _reject_unknown(value, {"condition_id", "provider", "model_id", "transport", "reasoning_effort"}, f"active_conditions[{index}]")
    required = {"condition_id", "provider", "model_id", "transport", "reasoning_effort"}
    missing = sorted(required - set(value))
    if missing:
        raise ModelMatrixError(f"active_conditions[{index}] is missing fields: {', '.join(missing)}")
    _validate_catalog_strings(value, f"active_conditions[{index}]")
    model_id = _non_empty_string(value["model_id"], f"active_conditions[{index}].model_id")
    if model_id.lower() in {"pending", "todo", "tbd", "unknown"} or "<" in model_id or ">" in model_id:
        raise ModelMatrixError(f"active_conditions[{index}].model_id cannot be a placeholder")
    transport = _non_empty_string(value["transport"], f"active_conditions[{index}].transport")
    if transport not in APPROVED_TRANSPORTS:
        raise ModelMatrixError(f"active_conditions[{index}].transport is not approved")
    reasoning_effort = value["reasoning_effort"]
    if reasoning_effort is not None:
        reasoning_effort = _non_empty_string(reasoning_effort, f"active_conditions[{index}].reasoning_effort")
    return MatrixCondition(
        condition_id=_safe_identifier(value["condition_id"], f"active_conditions[{index}].condition_id"),
        provider=_safe_identifier(value["provider"], f"active_conditions[{index}].provider"),
        model_id=model_id,
        transport=transport,
        reasoning_effort=reasoning_effort,
    )


def _parse_pending_condition(raw: Any, index: int) -> PendingMatrixCondition:
    value = _require_object(raw, f"pending_conditions[{index}]")
    _reject_unknown(value, {"condition_id", "provider", "display_name", "reason"}, f"pending_conditions[{index}]")
    required = {"condition_id", "provider", "display_name", "reason"}
    missing = sorted(required - set(value))
    if missing:
        raise ModelMatrixError(f"pending_conditions[{index}] is missing fields: {', '.join(missing)}")
    _validate_catalog_strings(value, f"pending_conditions[{index}]")
    return PendingMatrixCondition(
        condition_id=_safe_identifier(value["condition_id"], f"pending_conditions[{index}].condition_id"),
        provider=_safe_identifier(value["provider"], f"pending_conditions[{index}].provider"),
        display_name=_non_empty_string(value["display_name"], f"pending_conditions[{index}].display_name"),
        reason=_non_empty_string(value["reason"], f"pending_conditions[{index}].reason"),
    )


def load_model_matrix(path: Path) -> ModelMatrix:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelMatrixError(f"could not read model matrix: {type(exc).__name__}") from exc
    value = _require_object(raw, "model matrix")
    _reject_unknown(value, {"schema", "active_conditions", "pending_conditions"}, "model matrix")
    if value.get("schema") != MODEL_MATRIX_SCHEMA:
        raise ModelMatrixError("model matrix has an unsupported schema")
    active_raw = value.get("active_conditions")
    pending_raw = value.get("pending_conditions", [])
    if not isinstance(active_raw, list) or not active_raw:
        raise ModelMatrixError("active_conditions must be a non-empty list")
    if not isinstance(pending_raw, list):
        raise ModelMatrixError("pending_conditions must be a list")
    active = tuple(_parse_active_condition(item, index) for index, item in enumerate(active_raw))
    pending = tuple(_parse_pending_condition(item, index) for index, item in enumerate(pending_raw))
    condition_ids = [item.condition_id for item in (*active, *pending)]
    if len(set(condition_ids)) != len(condition_ids):
        raise ModelMatrixError("active and pending condition IDs must be unique")
    return ModelMatrix(active_conditions=active, pending_conditions=pending)


def _worker_command(
    project_root: Path,
    python_executable: Path,
    transport: str,
    *,
    max_rounds: int = MATRIX_MAX_ROUNDS,
    max_conversation_messages: int = MATRIX_MAX_CONVERSATION_MESSAGES,
    max_conversation_chars: int = MATRIX_MAX_CONVERSATION_CHARS,
) -> list[str]:
    worker = (project_root / "scripts" / "openai_compatible_workspace_worker.py").resolve()
    if not worker.is_file():
        raise ModelMatrixError(f"approved provider worker does not exist: {worker}")
    return [
        str(python_executable.resolve()),
        str(worker),
        "--transport",
        transport,
        "--max-rounds",
        str(max_rounds),
        "--max-conversation-messages",
        str(max_conversation_messages),
        "--max-conversation-chars",
        str(max_conversation_chars),
    ]


def build_registration_payload(
    conditions: tuple[MatrixCondition, ...],
    *,
    provider: str,
    mode: str,
    project_root: Path,
    python_executable: Path | None = None,
    harness_version: str = "0.1.0",
    batch_label: str = "v1",
    trial_timeout_seconds: float = TRIAL_TIMEOUT_SECONDS,
    worker_timeout_seconds: float = WORKER_TIMEOUT_SECONDS,
    worker_bounds: dict[str, int] | None = None,
    budget_overrides: dict[str, int] | None = None,
) -> dict[str, Any]:
    if not conditions:
        raise ModelMatrixError(f"provider {provider!r} has no active conditions")
    if mode not in {"smoke", "full"}:
        raise ModelMatrixError("mode must be smoke or full")
    root = project_root.resolve()
    interpreter = (python_executable or Path(sys.executable)).resolve()
    families = SMOKE_FAMILY_IDS if mode == "smoke" else FULL_FAMILY_IDS
    repetitions = SMOKE_REPETITIONS if mode == "smoke" else FULL_REPETITIONS
    _safe_identifier(batch_label, "batch_label")
    if trial_timeout_seconds <= worker_timeout_seconds:
        raise ModelMatrixError("trial_timeout_seconds must be greater than worker_timeout_seconds")
    bounds = {
        "max_rounds": MATRIX_MAX_ROUNDS,
        "max_conversation_messages": MATRIX_MAX_CONVERSATION_MESSAGES,
        "max_conversation_chars": MATRIX_MAX_CONVERSATION_CHARS,
    }
    if worker_bounds is not None:
        bounds.update(worker_bounds)
    if any(type(value) is not int or value <= 0 for value in bounds.values()):
        raise ModelMatrixError("worker bounds must be positive integers")
    batch_id = _safe_identifier(f"model-matrix-{provider}-{mode}-{batch_label}", "generated batch_id")
    payload = {
        "schema": "evidence-bounded-debugging-pilot-registration-v1",
        "batch_id": batch_id,
        "harness_version": harness_version,
        "case_root": str(root / "behavior_cases"),
        "family_ids": list(families),
        "repetitions": repetitions,
        "trial_timeout_seconds": trial_timeout_seconds,
        "artifacts_root": str(root / "results" / "model-matrix"),
        "workspace_parent": str(root / "results" / "model-matrix" / "workspaces"),
        "conditions": [
            {
                "condition_id": condition.condition_id,
                "provider": condition.provider,
                "model_id": condition.model_id,
                "adapter_id": APPROVED_ADAPTER_ID,
                "command": _worker_command(
                    root,
                    interpreter,
                    condition.transport,
                    max_rounds=bounds["max_rounds"],
                    max_conversation_messages=bounds["max_conversation_messages"],
                    max_conversation_chars=bounds["max_conversation_chars"],
                ),
                "reasoning_effort": condition.reasoning_effort,
                "network_required": True,
                "timeout_seconds": worker_timeout_seconds,
                "transport": condition.transport,
                "worker_bounds": bounds,
            }
            for condition in conditions
        ],
    }
    if budget_overrides:
        payload["budget_overrides"] = dict(sorted(budget_overrides.items()))
    return payload


def write_provider_registrations(
    matrix: ModelMatrix,
    output_dir: Path,
    *,
    project_root: Path,
    python_executable: Path | None = None,
    batch_label: str = "v1",
) -> tuple[Path, ...]:
    output = output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for provider in matrix.providers:
        conditions = matrix.conditions_for_provider(provider)
        for mode in ("smoke", "full"):
            destination = output / f"{provider}-{mode}.json"
            if destination.exists():
                raise ModelMatrixError(f"refusing to overwrite generated registration: {destination}")
            payload = build_registration_payload(
                conditions,
                provider=provider,
                mode=mode,
                project_root=project_root,
                python_executable=python_executable,
                batch_label=batch_label,
            )
            destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            written.append(destination)
    return tuple(written)
