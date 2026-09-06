"""Evidence-bounded debugging behavior study primitives."""

from .analysis import analyze_trace, compare_variants
from .calibration import calibrate_case_family
from .case_validation import validate_case_family
from .protocol import EvidenceSession
from .public import sanitize_public_run, sanitize_public_trace
from .runner import AgentResult, EvidenceTools, ModelCondition, run_unattended_trial, tool_contract
from .schema import CaseFamily, CaseVariant, ToolObservation, load_case_family

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
]
