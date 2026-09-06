from __future__ import annotations

from copy import deepcopy
from typing import Any


def sanitize_public_trace(record: dict[str, Any]) -> dict[str, Any]:
    """Remove answer-key annotations before a trace is copied into a public release."""
    sanitized = deepcopy(record)
    sanitized["variant_id"] = "redacted"
    for event in sanitized.get("events", []):
        event.pop("reveals", None)
    return sanitized


def sanitize_public_run(record: dict[str, Any]) -> dict[str, Any]:
    sanitized = deepcopy(record)
    sanitized["variant_id"] = "redacted"
    verifier = sanitized.get("verifier_result")
    if isinstance(verifier, dict):
        sanitized["verifier_result"] = {"status": verifier.get("status", "redacted")}
    return sanitized
