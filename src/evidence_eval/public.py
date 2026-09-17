from __future__ import annotations

from copy import deepcopy
import hashlib
import re
from typing import Any


PUBLIC_EXCLUDED_ARTIFACTS = ("adapter_result.json", "final_response.txt")
_PUBLIC_BATCH_FORBIDDEN_KEYS = frozenset(
    {
        "adapter_result",
        "api_key",
        "authorization",
        "case_root",
        "calibration",
        "command",
        "cwd",
        "environment",
        "hidden_cause",
        "password",
        "revealed_factors",
        "reveals",
        "secret",
        "token",
        "variant_slot",
        "variant_id",
        "verifier",
        "workspace_path",
    }
)
_PUBLIC_PATH_PATTERN = re.compile(r"(?:[A-Za-z]:\\|/(?:Users|home|workspace)/)")
_PUBLIC_RUN_ID_PATTERN = re.compile(r"^pub-[0-9a-f]{24}$")
_PUBLIC_PAIR_ID_PATTERN = re.compile(r"^pair-[0-9a-f]{24}$")


def derive_public_run_id(batch_id: str, internal_run_id: str) -> str:
    digest = hashlib.sha256(f"{batch_id}\0{internal_run_id}".encode("utf-8")).hexdigest()
    return f"pub-{digest[:24]}"


def derive_public_pair_id(batch_id: str, condition_id: str, family_id: str, repetition: int) -> str:
    value = f"{batch_id}\0{condition_id}\0{family_id}\0{repetition}"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"pair-{digest[:24]}"


def validate_public_batch_manifest(value: Any) -> None:
    """Reject batch manifests that contain internal fields or local paths."""
    if not isinstance(value, dict):
        raise ValueError("public batch manifest must be an object")

    def walk(item: Any, path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in _PUBLIC_BATCH_FORBIDDEN_KEYS:
                    raise ValueError(f"public batch manifest contains forbidden field: {path}.{key}")
                if key == "run_id" and (not isinstance(child, str) or not _PUBLIC_RUN_ID_PATTERN.fullmatch(child)):
                    raise ValueError(f"public batch manifest contains a non-opaque run id: {path}.{key}")
                if key == "pair_id" and (not isinstance(child, str) or not _PUBLIC_PAIR_ID_PATTERN.fullmatch(child)):
                    raise ValueError(f"public batch manifest contains an invalid pair id: {path}.{key}")
                walk(child, f"{path}.{key}")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{path}[{index}]")
        elif isinstance(item, str) and _PUBLIC_PATH_PATTERN.search(item):
            raise ValueError(f"public batch manifest contains a local path: {path}")

    walk(value, "$")


def sanitize_public_trace(record: dict[str, Any]) -> dict[str, Any]:
    """Remove answer-key annotations and workspace payloads from a public trace."""

    def redact(item: Any) -> Any:
        if isinstance(item, dict):
            result: dict[str, Any] = {}
            for key, value in item.items():
                if key in {"variant_id", "variant_slot", "revealed_factors", "reveals"}:
                    continue
                if key == "content":
                    if isinstance(value, str):
                        result["content_chars"] = len(value)
                        result["content_redacted"] = True
                    continue
                result[key] = redact(value)
            return result
        if isinstance(item, list):
            return [redact(value) for value in item]
        return deepcopy(item)

    return redact(record)


def sanitize_public_run(record: dict[str, Any]) -> dict[str, Any]:
    sanitized = deepcopy(record)
    for key in ("verifier_id", "declaration", "expected_cause", "hidden_cause", "calibration", "checks", "regressions"):
        sanitized.pop(key, None)
    if "variant_id" in sanitized:
        sanitized.pop("variant_id", None)
    if "variant_slot" in sanitized:
        sanitized.pop("variant_slot", None)
    if "run_id" in sanitized and not _PUBLIC_RUN_ID_PATTERN.fullmatch(str(sanitized["run_id"])):
        sanitized.pop("run_id", None)
    if "pair_id" in sanitized and not _PUBLIC_PAIR_ID_PATTERN.fullmatch(str(sanitized["pair_id"])):
        sanitized.pop("pair_id", None)
    verifier = sanitized.get("verifier_result")
    if isinstance(verifier, dict):
        projected = {"status": verifier.get("status", "redacted")}
        if isinstance(verifier.get("passed"), bool):
            projected["passed"] = verifier["passed"]
        sanitized["verifier_result"] = projected
    return sanitized


def sanitize_public_verifier_result(record: dict[str, Any]) -> dict[str, Any]:
    """Keep only non-declarative verifier outcome fields."""
    projected = {"status": record.get("status", "redacted")}
    if isinstance(record.get("passed"), bool):
        projected["passed"] = record["passed"]
    return projected


def sanitize_public_case_family(raw: dict[str, Any]) -> dict[str, Any]:
    """Create a public case summary without fixture or answer-key content."""
    allowed = (
        "family_id",
        "dimension",
        "initial_context",
        "allowed_actions",
        "action_costs",
        "max_cost",
        "max_events",
    )
    sanitized = {key: deepcopy(raw[key]) for key in allowed if key in raw}
    variants = raw.get("variants", [])
    sanitized["variant_count"] = len(variants) if isinstance(variants, list) else 0
    perturbations = raw.get("perturbations", [])
    sanitized["perturbations"] = [
        {"type": item.get("type", "controlled-intervention")}
        for item in perturbations
        if isinstance(item, dict)
    ]
    return sanitized


def sanitize_public_batch_manifest(raw: dict[str, Any], public_trials: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Project an internal batch manifest to safe, opaque public trial metadata."""
    if not isinstance(raw, dict):
        raise ValueError("batch manifest must be an object")
    batch_id = raw.get("batch_id")
    if not isinstance(batch_id, str):
        raise ValueError("batch manifest must contain a string batch_id")

    def trial_projection(entry: Any) -> dict[str, Any]:
        if not isinstance(entry, dict) or not isinstance(entry.get("run_id"), str):
            raise ValueError("batch trial entry must contain a string run_id")
        internal_id = entry["run_id"]
        info = public_trials.get(internal_id)
        if not isinstance(info, dict):
            raise ValueError(f"missing public trial mapping for {internal_id}")
        projected = {
            key: deepcopy(entry[key])
            for key in (
                "adapter_id",
                "condition_id",
                "family_id",
                "model_id",
                "provider",
                "repetition",
                "execution_status",
                "infrastructure_censored",
                "verifier_passed",
                "verifier_status",
            )
            if key in entry
        }
        projected["run_id"] = info["public_run_id"]
        projected["pair_id"] = info["pair_id"]
        return projected

    projected: dict[str, Any] = {
        key: deepcopy(raw[key])
        for key in (
            "schema",
            "batch_id",
            "case_set_hash",
            "completed_at_utc_epoch",
            "harness_version",
            "registration_hash",
            "started_at_utc_epoch",
            "source_revision",
            "trial_timeout_seconds",
            "budget_overrides",
            "registration_summary",
        )
        if key in raw
    }
    projected["conditions"] = [
        {
            key: deepcopy(condition[key])
            for key in (
                "condition_id",
                "provider",
                "model_id",
                "adapter_id",
                "reasoning_effort",
                "network_required",
                "transport",
                "timeout_seconds",
                "worker_bounds",
            )
            if key in condition
        }
        for condition in raw.get("conditions", [])
        if isinstance(condition, dict)
    ]
    projected["planned_trials"] = [trial_projection(entry) for entry in raw.get("planned_trials", [])]
    projected["results"] = [trial_projection(entry) for entry in raw.get("results", [])]
    if isinstance(raw.get("aggregates"), list):
        projected["aggregates"] = deepcopy(raw["aggregates"])
    validate_public_batch_manifest(projected)
    return projected


def sanitize_public_artifact(name: str, value: Any) -> Any:
    if name in PUBLIC_EXCLUDED_ARTIFACTS:
        raise ValueError(f"raw adapter artifact is not publishable: {name}")
    if name == "manifest.json":
        validate_public_batch_manifest(value)
        return deepcopy(value)
    if name == "run.json" and isinstance(value, dict):
        return sanitize_public_run(value)
    if name == "verifier_result.json" and isinstance(value, dict):
        return sanitize_public_verifier_result(value)
    if name in {"event_trace.json", "behavioral_annotations.json"} and isinstance(value, dict):
        return sanitize_public_trace(value)
    return deepcopy(value)
