from __future__ import annotations

from typing import Any

from .schema import CaseFamily


def validate_case_family(family: CaseFamily) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if len(family.variants) < 2:
        errors.append("a behavioral case family requires at least two variants")
    if len(set(variant.variant_id for variant in family.variants)) != len(family.variants):
        errors.append("variant IDs must be unique")
    if not family.perturbations:
        errors.append("a case family requires at least one declared perturbation")
    if family.max_cost <= 0:
        errors.append("max_cost must be positive")
    if any(cost < 0 for cost in family.action_costs.values()):
        errors.append("action costs cannot be negative")

    signatures = {variant.surface_signature for variant in family.variants}
    if len(signatures) > 1:
        errors.append("all variants must share a surface signature")

    for variant in family.variants:
        if len(variant.hypotheses) < 2:
            errors.append(f"{variant.variant_id}: requires at least two hypotheses")
        if not any(path.endswith((".ts", ".tsx")) for path in variant.files):
            errors.append(f"{variant.variant_id}: requires TypeScript or TSX source")
        if variant.verifier.get("expected_cause") != variant.hidden_cause:
            errors.append(f"{variant.variant_id}: verifier expected_cause must match hidden_cause")
        seen: set[tuple[str, str]] = set()
        for observation in variant.observations:
            key = (observation.action, observation.target)
            if key in seen:
                errors.append(f"{variant.variant_id}: duplicate observation {key}")
            seen.add(key)
            if observation.action not in family.allowed_actions:
                errors.append(f"{variant.variant_id}: observation uses unsupported action {observation.action}")
            if observation.action not in family.action_costs:
                errors.append(f"{variant.variant_id}: observation has no action cost for {observation.action}")

    if len(family.variants) >= 2:
        first, *rest = family.variants
        for other in rest:
            shared_keys = {
                (item.action, item.target) for item in first.observations
            } & {
                (item.action, item.target) for item in other.observations
            }
            discriminating = any(
                first.observation_for(*key).content != other.observation_for(*key).content
                or first.observation_for(*key).reveals != other.observation_for(*key).reveals
                for key in shared_keys
            )
            if not discriminating:
                errors.append(f"{first.variant_id}/{other.variant_id}: no shared action discriminates variants")

    if not any("counterfactual" in str(item).lower() for item in family.perturbations):
        warnings.append("perturbation list does not explicitly name a counterfactual")
    return {
        "family_id": family.family_id,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "variant_count": len(family.variants),
    }
