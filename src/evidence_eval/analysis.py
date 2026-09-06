from __future__ import annotations

from collections import Counter
from typing import Any


def analyze_trace(record: dict[str, Any]) -> dict[str, Any]:
    events = list(record.get("events", []))
    accepted = [event for event in events if event.get("kind") == "action" and event.get("accepted")]
    checkpoints = [event for event in events if event.get("kind") == "checkpoint"]
    first_edit = next((event for event in accepted if event.get("action") == "edit"), None)
    first_action = accepted[0] if accepted else None
    revealed = sorted({item for event in accepted for item in event.get("reveals", [])})
    return {
        "family_id": record.get("family_id"),
        "variant_id": record.get("variant_id"),
        "status": record.get("status"),
        "action_sequence": [event.get("action") for event in accepted],
        "target_sequence": [event.get("target") for event in accepted],
        "action_counts": dict(Counter(event.get("action") for event in accepted)),
        "first_action": first_action.get("action") if first_action else None,
        "first_target": first_action.get("target") if first_action else None,
        "actions_before_first_edit": next(
            (index for index, event in enumerate(accepted) if event.get("action") == "edit"),
            None,
        ),
        "first_edit_target": first_edit.get("target") if first_edit else None,
        "checkpoint_count": len(checkpoints),
        "leading_hypotheses": [event.get("leading_hypothesis") for event in checkpoints],
        "confidence_sequence": [event.get("confidence") for event in checkpoints],
        "revealed_factors": revealed,
        "rejected_action_count": sum(event.get("kind") == "rejected_action" for event in events),
        "remaining_cost": record.get("remaining_cost"),
    }


def compare_variants(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    decision_fields = (
        "first_action",
        "first_target",
        "action_sequence",
        "first_edit_target",
        "leading_hypotheses",
        "confidence_sequence",
    )
    environment_fields = ("revealed_factors", "rejected_action_count", "remaining_cost")
    changed = [field for field in decision_fields if first.get(field) != second.get(field)]
    environment_changed = [field for field in environment_fields if first.get(field) != second.get(field)]
    return {
        "first_variant": first.get("variant_id"),
        "second_variant": second.get("variant_id"),
        "changed_fields": changed,
        "behavior_changed": bool(changed),
        "environment_changed_fields": environment_changed,
        "environment_changed": bool(environment_changed),
        "comparison_is_causal_only_if_pre_registered": True,
    }
