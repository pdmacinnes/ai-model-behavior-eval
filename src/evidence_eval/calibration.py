from __future__ import annotations

from typing import Any

from .schema import CaseFamily, CaseVariant


def _calibrate_variant(variant: CaseVariant) -> dict[str, Any]:
    errors: list[str] = []
    calibration = variant.calibration
    visible = calibration.get("visible_test", {})
    mutation = calibration.get("mutation_proof", {})

    if visible.get("status") != "fails_before_fix":
        errors.append("visible_test.status must be fails_before_fix")
    if visible.get("surface_signature") != variant.surface_signature:
        errors.append("visible_test.surface_signature must match surface_signature")
    if not visible.get("test_id"):
        errors.append("visible_test.test_id is required")

    path = mutation.get("path")
    before = mutation.get("before")
    after = mutation.get("after")
    if not isinstance(path, str) or path not in variant.files:
        errors.append("mutation_proof.path must identify a case file")
    elif not isinstance(before, str) or not before:
        errors.append("mutation_proof.before is required")
    elif variant.files[path].count(before) != 1:
        errors.append("mutation_proof.before must occur exactly once in its source file")
    elif not isinstance(after, str) or not after or after == before:
        errors.append("mutation_proof.after must be a distinct non-empty replacement")

    if mutation.get("preserves_surface_signature") is not True:
        errors.append("mutation_proof must declare preserves_surface_signature=true")

    return {
        "variant_id": variant.variant_id,
        "valid": not errors,
        "errors": errors,
        "visible_test": {
            "test_id": visible.get("test_id"),
            "status": visible.get("status"),
            "surface_signature": visible.get("surface_signature"),
        },
        "mutation_proof": {
            "path": path,
            "replacement_applied": not errors and isinstance(path, str),
            "preserves_surface_signature": mutation.get("preserves_surface_signature"),
        },
        "authoritative_verifier": {
            "expected_cause": variant.verifier.get("expected_cause"),
            "required_behavior": variant.verifier.get("required_behavior"),
        },
    }


def calibrate_case_family(family: CaseFamily) -> dict[str, Any]:
    errors: list[str] = []
    variants = [_calibrate_variant(variant) for variant in family.variants]
    errors.extend(
        f"{item['variant_id']}: {error}"
        for item in variants
        for error in item["errors"]
    )

    test_ids = {
        item["visible_test"].get("test_id")
        for item in variants
        if item["visible_test"].get("test_id")
    }
    if len(test_ids) != 1:
        errors.append("all variants must calibrate against the same visible test")

    signatures = {
        item["visible_test"].get("surface_signature")
        for item in variants
        if item["visible_test"].get("surface_signature")
    }
    if len(signatures) != 1 or signatures != {variant.surface_signature for variant in family.variants}:
        errors.append("counterfactual calibration must preserve one surface signature")

    return {
        "family_id": family.family_id,
        "valid": not errors,
        "errors": errors,
        "visible_test_id": next(iter(test_ids), None),
        "surface_signature": next(iter(signatures), None),
        "variants": variants,
    }
