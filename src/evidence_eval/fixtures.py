"""Dependency-free authoring calibration, not an authoritative model grader."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schema import CaseFamily, CaseVariant


@dataclass(frozen=True)
class FixtureOutcome:
    test_id: str
    passed: bool
    observed: dict[str, Any]
    surface: dict[str, Any]


def _dashboard_outcome(files: dict[str, str], test_id: str) -> FixtureOutcome:
    page = files["app/dashboard/page.tsx"]
    fetch = files["lib/fetchMetrics.ts"]
    cache = files["lib/cache.ts"]
    request_has_range = "getMetrics(params.range)" in page and ("?range=" in fetch or "?range=" in cache)
    cache_is_safe = "cachedMetrics" not in fetch or "['metrics', range]" in cache or '[\"metrics\", range]' in cache
    observed_range = 30 if request_has_range and cache_is_safe else 7
    return FixtureOutcome(
        test_id=test_id,
        passed=observed_range == 30,
        observed={
            "requested_range": 30,
            "observed_range": observed_range,
            "request_has_range": request_has_range,
            "cache_is_safe": cache_is_safe,
        },
        surface={"chart_stale_until_refresh": observed_range != 30},
    )


def _session_outcome(files: dict[str, str], test_id: str) -> FixtureOutcome:
    session = files["lib/session.ts"]
    component = files["components/RoleSwitcher.tsx"]
    server_current = "refreshSession" in session or "cache: 'no-store'" in session
    client_current = "useSessionCache" not in component or "invalidateOn" in component
    observed_role = "admin" if server_current and client_current else "viewer"
    return FixtureOutcome(
        test_id=test_id,
        passed=observed_role == "admin",
        observed={
            "expected_role": "admin",
            "observed_role": observed_role,
            "server_current": server_current,
            "client_current": client_current,
        },
        surface={"admin_nav_stale_until_refresh": observed_role != "admin"},
    )


def _pagination_outcome(files: dict[str, str], test_id: str) -> FixtureOutcome:
    page = files["app/orders/page.tsx"]
    orders = files["lib/orders.ts"]
    page_reaches_service = "getOrders(page)" in page
    uses_page_parameter = "?page=${page}" in orders
    offset_is_zero_based = "(page - 1) * PAGE_SIZE" in orders
    server_propagates_page = page_reaches_service and (uses_page_parameter or "const offset =" in orders)
    distinct_records = page_reaches_service and (uses_page_parameter or offset_is_zero_based)
    return FixtureOutcome(
        test_id=test_id,
        passed=distinct_records,
        observed={
            "expected_distinct_records": True,
            "distinct_records": distinct_records,
            "server_propagates_page": server_propagates_page,
            "offset_is_zero_based": offset_is_zero_based,
        },
        surface={"page_two_repeats_page_one": not distinct_records},
    )


def run_visible_fixture(family: CaseFamily, variant: CaseVariant, files: dict[str, str]) -> FixtureOutcome:
    test_id = str(variant.calibration["visible_test"]["test_id"])
    if family.family_id == "dashboard-filter-refresh":
        return _dashboard_outcome(files, test_id)
    if family.family_id == "session-refresh-role":
        return _session_outcome(files, test_id)
    if family.family_id == "pagination-offset":
        return _pagination_outcome(files, test_id)
    raise ValueError(f"no executable fixture registered for {family.family_id!r}")


def infer_cause(family: CaseFamily, outcome: FixtureOutcome) -> str | None:
    if family.family_id == "dashboard-filter-refresh":
        if not outcome.observed["request_has_range"]:
            return "query propagation"
        if not outcome.observed["cache_is_safe"]:
            return "cache key behavior"
    elif family.family_id == "session-refresh-role":
        if not outcome.observed["server_current"]:
            return "server session prop"
        if not outcome.observed["client_current"]:
            return "client session cache"
    elif family.family_id == "pagination-offset":
        if not outcome.observed["server_propagates_page"]:
            return "server page ignored"
        if not outcome.observed["offset_is_zero_based"] and not outcome.observed["distinct_records"]:
            return "API offset base"
    return None


def authoritative_verify(family: CaseFamily, variant: CaseVariant, outcome: FixtureOutcome) -> dict[str, Any]:
    inferred_cause = infer_cause(family, outcome)
    return {
        "status": "passed" if outcome.passed and inferred_cause is None else "failed",
        "expected_cause": variant.verifier.get("expected_cause"),
        "inferred_cause_after_fix": inferred_cause,
        "required_behavior": variant.verifier.get("required_behavior"),
    }


def mutation_steps(variant: CaseVariant) -> list[dict[str, Any]]:
    mutation = variant.calibration["mutation_proof"]
    return list(mutation.get("replacements") or [mutation])


def apply_declared_mutation(
    variant: CaseVariant,
    *,
    excluded_indices: set[int] | None = None,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    files = dict(variant.files)
    excluded = excluded_indices or set()
    steps = mutation_steps(variant)
    applied: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        if index in excluded:
            continue
        path = str(step["path"])
        before = str(step["before"])
        after = str(step["after"])
        source = files[path]
        if source.count(before) != 1:
            raise ValueError(f"{variant.variant_id}: mutation text is not unique in {path}")
        if before == after:
            raise ValueError(f"{variant.variant_id}: mutation step {index} is a no-op")
        files[path] = source.replace(before, after, 1)
        changed = files[path] != source
        if not changed:
            raise ValueError(f"{variant.variant_id}: mutation step {index} did not change its file")
        applied.append({"index": index, "path": path, "before_occurrences": 1, "changed": changed})
    return files, applied
