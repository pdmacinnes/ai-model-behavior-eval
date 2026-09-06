from __future__ import annotations

import json
from typing import Any

from .fixtures import authoritative_verify, apply_declared_mutation, infer_cause, mutation_steps, run_visible_fixture
from .schema import CaseFamily, CaseVariant


def _calibrate_variant(family: CaseFamily, variant: CaseVariant) -> dict[str, Any]:
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

    try:
        before = run_visible_fixture(family, variant, variant.files)
    except (KeyError, ValueError) as exc:
        errors.append(f"fixture setup failed before mutation: {exc}")
        before = None
    if before is not None and before.passed:
        errors.append("visible fixture unexpectedly passes before the declared fix")
    if before is not None and infer_cause(family, before) != variant.verifier.get("expected_cause"):
        errors.append("pre-fix inferred cause does not match the authoritative expected cause")

    applied: list[dict[str, Any]] = []
    after = None
    verifier: dict[str, Any] = {"status": "not_run"}
    try:
        mutated_files, applied = apply_declared_mutation(variant)
        after = run_visible_fixture(family, variant, mutated_files)
        verifier = authoritative_verify(family, variant, after)
    except (KeyError, ValueError) as exc:
        errors.append(f"fixture mutation failed: {exc}")

    if after is not None and not after.passed:
        errors.append("visible fixture still fails after the declared mutation")
    if verifier.get("status") != "passed":
        errors.append("authoritative verifier did not pass after the declared mutation")
    steps = mutation_steps(variant)
    for index in range(len(steps)):
        try:
            partial_files, _ = apply_declared_mutation(variant, excluded_indices={index})
            partial_outcome = run_visible_fixture(family, variant, partial_files)
        except (KeyError, ValueError) as exc:
            errors.append(f"fixture necessity check failed for mutation {index}: {exc}")
            continue
        if partial_outcome.passed:
            errors.append(f"mutation step {index} is not necessary for the visible fix")
    if mutation.get("preserves_surface_signature") is not True:
        errors.append("mutation_proof must declare preserves_surface_signature=true")

    return {
        "variant_id": variant.variant_id,
        "valid": not errors,
        "errors": errors,
        "visible_test": {
            "test_id": visible.get("test_id"),
            "declared_status": visible.get("status"),
            "before_passed": before.passed if before is not None else None,
            "after_passed": after.passed if after is not None else None,
            "surface_signature": visible.get("surface_signature"),
            "before_surface": before.surface if before is not None else None,
        },
        "mutation_proof": {
            "replacement_count": len(applied),
            "replacement_preview_valid": bool(applied) and all(item["changed"] for item in applied),
            "necessity_checked": True,
            "preserves_surface_signature": mutation.get("preserves_surface_signature"),
            "applied_paths": [item["path"] for item in applied],
        },
        "authoritative_verifier": verifier,
    }


def calibrate_case_family(family: CaseFamily) -> dict[str, Any]:
    errors: list[str] = []
    variants = [_calibrate_variant(family, variant) for variant in family.variants]
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
    surface_vectors = {
        json.dumps(item["visible_test"].get("before_surface"), sort_keys=True)
        for item in variants
    }
    if len(surface_vectors) != 1:
        errors.append("counterfactual variants must share the same measured pre-fix surface vector")

    return {
        "family_id": family.family_id,
        "valid": not errors,
        "calibration_mode": "executable_dependency_free_fixture",
        "errors": errors,
        "visible_test_id": next(iter(test_ids), None),
        "surface_signature": next(iter(signatures), None),
        "variants": variants,
    }
