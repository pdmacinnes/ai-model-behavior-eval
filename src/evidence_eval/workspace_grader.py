from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from .schema import CaseFamily, CaseVariant


@dataclass(frozen=True)
class WorkspaceVerifierResult:
    verifier_id: str
    status: str
    passed: bool
    checks: dict[str, bool]
    regressions: list[str]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WorkspaceVerifier(Protocol):
    def __call__(self, family: CaseFamily, variant: CaseVariant, workspace: Path) -> WorkspaceVerifierResult: ...


def not_configured_workspace_verifier(
    family: CaseFamily,
    variant: CaseVariant,
    workspace: Path,
) -> WorkspaceVerifierResult:
    """Fail closed until a case-specific runtime verifier is registered."""
    del variant, workspace
    return WorkspaceVerifierResult(
        verifier_id=f"{family.family_id}:not-configured",
        status="not_configured",
        passed=False,
        checks={},
        regressions=[],
        error="no authoritative workspace verifier is configured for this case family",
    )


def invoke_workspace_verifier(
    verifier: WorkspaceVerifier | None,
    family: CaseFamily,
    variant: CaseVariant,
    workspace: Path,
) -> WorkspaceVerifierResult:
    if verifier is None:
        return not_configured_workspace_verifier(family, variant, workspace)
    try:
        result = verifier(family, variant, workspace)
        if not isinstance(result, WorkspaceVerifierResult):
            raise TypeError("workspace verifiers must return WorkspaceVerifierResult")
        return result
    except Exception as exc:  # verifier failures are recorded, never treated as a pass
        return WorkspaceVerifierResult(
            verifier_id=f"{family.family_id}:error",
            status="error",
            passed=False,
            checks={},
            regressions=[],
            error=f"{type(exc).__name__}: {exc}",
        )
