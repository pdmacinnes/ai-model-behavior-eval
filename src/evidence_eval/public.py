from __future__ import annotations

from copy import deepcopy
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
        "variant_id",
        "verifier",
        "workspace_path",
    }
)
_PUBLIC_PATH_PATTERN = re.compile(r"(?:[A-Za-z]:\\|/(?:Users|home|workspace)/)")


def validate_public_batch_manifest(value: Any) -> None:
    """Reject batch manifests that contain internal fields or local paths."""
    if not isinstance(value, dict):
        raise ValueError("public batch manifest must be an object")

    def walk(item: Any, path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in _PUBLIC_BATCH_FORBIDDEN_KEYS:
                    raise ValueError(f"public batch manifest contains forbidden field: {path}.{key}")
                walk(child, f"{path}.{key}")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{path}[{index}]")
        elif isinstance(item, str) and _PUBLIC_PATH_PATTERN.search(item):
            raise ValueError(f"public batch manifest contains a local path: {path}")

    walk(value, "$")


def sanitize_public_trace(record: dict[str, Any]) -> dict[str, Any]:
    """Remove answer-key annotations before a trace is copied into a public release."""
    sanitized = deepcopy(record)
    sanitized["variant_id"] = "redacted"
    sanitized.pop("revealed_factors", None)
    for event in sanitized.get("events", []):
        event.pop("reveals", None)
    annotations = sanitized.get("behavioral_annotations")
    if isinstance(annotations, dict):
        annotations.pop("revealed_factors", None)
    nested_trace = sanitized.get("trace")
    if isinstance(nested_trace, dict):
        sanitized["trace"] = sanitize_public_trace(nested_trace)
    return sanitized


def sanitize_public_run(record: dict[str, Any]) -> dict[str, Any]:
    sanitized = deepcopy(record)
    sanitized["variant_id"] = "redacted"
    verifier = sanitized.get("verifier_result")
    if isinstance(verifier, dict):
        sanitized["verifier_result"] = {"status": verifier.get("status", "redacted")}
    return sanitized


def sanitize_public_case_family(raw: dict[str, Any]) -> dict[str, Any]:
    """Create a model-facing case pack without hidden causes or grader metadata."""
    sanitized = deepcopy(raw)
    variants = sanitized.get("variants", [])
    for index, variant in enumerate(variants, start=1):
        variant["variant_id"] = f"variant-{index}"
        variant.pop("hidden_cause", None)
        variant.pop("verifier", None)
        variant.pop("calibration", None)
        for observation in variant.get("observations", []):
            observation.pop("reveals", None)
    sanitized["perturbations"] = [
        {"type": item.get("type", "controlled-intervention")}
        for item in sanitized.get("perturbations", [])
    ]
    return sanitized


def sanitize_public_artifact(name: str, value: Any) -> Any:
    if name in PUBLIC_EXCLUDED_ARTIFACTS:
        raise ValueError(f"raw adapter artifact is not publishable: {name}")
    if name == "manifest.json":
        validate_public_batch_manifest(value)
        return deepcopy(value)
    if name in {"run.json", "verifier_result.json"} and isinstance(value, dict):
        return sanitize_public_run(value)
    if name in {"event_trace.json", "behavioral_annotations.json"} and isinstance(value, dict):
        return sanitize_public_trace(value)
    return deepcopy(value)
