from __future__ import annotations

from collections import Counter
from typing import Any


def analyze_trace(record: dict[str, Any]) -> dict[str, Any]:
    events = list(record.get("events", []))
    accepted = [event for event in events if event.get("kind") == "action" and event.get("accepted")]
    checkpoints = [event for event in events if event.get("kind") == "checkpoint"]
    rejected = [event for event in events if event.get("kind") == "rejected_action"]
    first_edit = next((event for event in accepted if event.get("action") == "edit"), None)
    first_action = accepted[0] if accepted else None
    stop_event = next((event for event in reversed(events) if event.get("kind") == "stop"), None)
    edit_count = sum(event.get("action") == "edit" for event in accepted)
    revealed = sorted({item for event in accepted for item in event.get("reveals", [])})
    budget_depleted = record.get("remaining_cost") == 0
    action_rejected_for_insufficient_budget = any(
        event.get("error") == "evidence budget exceeded" for event in rejected
    )
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
        "repair_attempted": edit_count > 0,
        "edit_count": edit_count,
        "termination_reason": stop_event.get("reason") if stop_event else None,
        "budget_depleted": budget_depleted,
        "action_rejected_for_insufficient_budget": action_rejected_for_insufficient_budget,
        "budget_exhausted": budget_depleted or action_rejected_for_insufficient_budget,
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
