"""Evidence-bounded debugging behavior study primitives."""

from .analysis import analyze_trace, compare_variants
from .calibration import calibrate_case_family
from .case_validation import validate_case_family
from .protocol import EvidenceSession
from .public import sanitize_public_run, sanitize_public_trace
from .runner import AgentResult, EvidenceTools, ModelCondition, run_unattended_trial, tool_contract
from .schema import CaseFamily, CaseVariant, ToolObservation, load_case_family
from .workspace import MaterializedWorkspace, WorkspaceMaterializationError, materialize_variant
from .workspace_grader import (
    WorkspaceVerifierResult,
    invoke_workspace_verifier,
    not_configured_workspace_verifier,
)
from .workspace_runner import WorkspaceTools, run_workspace_trial, workspace_tool_contract
from .workspace_verifiers import registered_workspace_verifier

__all__ = [
    "CaseFamily",
    "CaseVariant",
    "AgentResult",
    "EvidenceSession",
    "EvidenceTools",
    "ModelCondition",
    "ToolObservation",
    "analyze_trace",
    "calibrate_case_family",
    "compare_variants",
    "run_unattended_trial",
    "sanitize_public_run",
    "sanitize_public_trace",
    "tool_contract",
    "load_case_family",
    "validate_case_family",
    "MaterializedWorkspace",
    "WorkspaceMaterializationError",
    "materialize_variant",
    "WorkspaceVerifierResult",
    "invoke_workspace_verifier",
    "not_configured_workspace_verifier",
    "WorkspaceTools",
    "run_workspace_trial",
    "workspace_tool_contract",
    "registered_workspace_verifier",
]
