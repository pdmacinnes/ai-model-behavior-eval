"""Case-specific source invariant verifiers for the pilot workspace snapshots.

These verifiers are separate from dependency-free authoring calibration. They inspect
the materialized workspace after an adapter run and do not import or call fixtures.py.
They verify the pilot's source-level postconditions, not a full Next.js runtime.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from .schema import CaseFamily, CaseVariant
from .workspace_grader import WorkspaceVerifier, WorkspaceVerifierResult


_TOKEN_PATTERN = re.compile(
    r"`(?:\\.|[^`])*`|'(?:\\.|[^'])*'|\"(?:\\.|[^\"])*\"|[A-Za-z_$][A-Za-z0-9_$]*|\d+|===|!==|=>|==|!=|&&|\|\||[{}()[\].,:;?=+*/-]"
)
_COMMENT_PATTERN = re.compile(r"/\*.*?\*/|//[^\r\n]*", re.DOTALL)


def _tokens(source: str) -> list[str]:
    return _TOKEN_PATTERN.findall(_COMMENT_PATTERN.sub("", source))


def _contains(tokens: list[str], sequence: list[str]) -> bool:
    width = len(sequence)
    return any(tokens[index : index + width] == sequence for index in range(len(tokens) - width + 1))


def _read(workspace: Path, relative: str) -> str | None:
    path = workspace / Path(relative)
    try:
        return path.read_text(encoding="utf-8") if path.is_file() else None
    except (OSError, UnicodeError):
        return None


def _result(verifier_id: str, checks: dict[str, bool]) -> WorkspaceVerifierResult:
    regressions = [name for name, passed in checks.items() if not passed]
    return WorkspaceVerifierResult(
        verifier_id=verifier_id,
        status="passed" if not regressions else "failed",
        passed=not regressions,
        checks=checks,
        regressions=regressions,
    )


def _dashboard_query_verifier(family: CaseFamily, variant: CaseVariant, workspace: Path) -> WorkspaceVerifierResult:
    page = _read(workspace, "app/dashboard/page.tsx") or ""
    fetch = _read(workspace, "lib/fetchMetrics.ts") or ""
    page_tokens = _tokens(page)
    fetch_tokens = _tokens(fetch)
    return _result(
        "dashboard-filter-refresh:query-omitted-v1",
        {
            "page_passes_selected_range": _contains(page_tokens, ["getMetrics", "(", "params", ".", "range", ")"]),
            "request_template_uses_range": any("?range=${range}" in token for token in fetch_tokens),
        },
    )


def _dashboard_cache_verifier(family: CaseFamily, variant: CaseVariant, workspace: Path) -> WorkspaceVerifierResult:
    cache = _read(workspace, "lib/cache.ts") or ""
    tokens = _tokens(cache)
    return _result(
        "dashboard-filter-refresh:cache-key-v1",
        {"cache_key_includes_range": _contains(tokens, ["[", "'metrics'", ",", "range", "]"]) or _contains(tokens, ['[', '"metrics"', ",", "range", "]"])},
    )


def _session_server_verifier(family: CaseFamily, variant: CaseVariant, workspace: Path) -> WorkspaceVerifierResult:
    session = _read(workspace, "lib/session.ts") or ""
    return _result(
        "session-refresh-role:server-session-prop-v1",
        {"session_reads_refreshed_context": _contains(_tokens(session), ["requestContext", ".", "refreshSession", "(", ")"])},
    )


def _session_client_verifier(family: CaseFamily, variant: CaseVariant, workspace: Path) -> WorkspaceVerifierResult:
    component = _read(workspace, "components/RoleSwitcher.tsx") or ""
    tokens = _tokens(component)
    return _result(
        "session-refresh-role:client-session-cache-v1",
        {"client_cache_invalidates_on_role_change": _contains(tokens, ["useSessionCache", "(", "initialRole", ",", "{", "invalidateOn", ":", "'role-change'", "}"])},
    )


def _pagination_server_verifier(family: CaseFamily, variant: CaseVariant, workspace: Path) -> WorkspaceVerifierResult:
    page = _read(workspace, "app/orders/page.tsx") or ""
    orders = _read(workspace, "lib/orders.ts") or ""
    return _result(
        "pagination-offset:server-page-ignored-v1",
        {
            "page_reaches_order_service": _contains(_tokens(page), ["getOrders", "(", "page", ")"]),
            "request_template_uses_page": any("?page=${page}" in token for token in _tokens(orders)),
        },
    )


def _pagination_offset_verifier(family: CaseFamily, variant: CaseVariant, workspace: Path) -> WorkspaceVerifierResult:
    orders = _read(workspace, "lib/orders.ts") or ""
    return _result(
        "pagination-offset:api-offset-base-v1",
        {"offset_uses_zero_based_page": _contains(_tokens(orders), ["const", "offset", "=", "(", "page", "-", "1", ")", "*", "PAGE_SIZE"])},
    )


_REGISTERED: dict[tuple[str, str], Callable[[CaseFamily, CaseVariant, Path], WorkspaceVerifierResult]] = {
    ("dashboard-filter-refresh", "query-omitted"): _dashboard_query_verifier,
    ("dashboard-filter-refresh", "cache-key-static"): _dashboard_cache_verifier,
    ("session-refresh-role", "server-session-prop"): _session_server_verifier,
    ("session-refresh-role", "client-session-cache"): _session_client_verifier,
    ("pagination-offset", "server-page-ignored"): _pagination_server_verifier,
    ("pagination-offset", "api-offset-base"): _pagination_offset_verifier,
}


def registered_workspace_verifier(family: CaseFamily) -> WorkspaceVerifier | None:
    if not any(key[0] == family.family_id for key in _REGISTERED):
        return None

    def verify(received_family: CaseFamily, variant: CaseVariant, workspace: Path) -> WorkspaceVerifierResult:
        verifier = _REGISTERED.get((received_family.family_id, variant.variant_id))
        if verifier is None:
            return WorkspaceVerifierResult(
                verifier_id=f"{received_family.family_id}:unregistered-variant",
                status="not_configured",
                passed=False,
                checks={},
                regressions=[],
                error="no source-level verifier is registered for this variant",
            )
        return verifier(received_family, variant, workspace)

    return verify
