"""Evidence-bounded debugging behavior study primitives."""

from .analysis import analyze_trace, compare_variants
from .case_validation import validate_case_family
from .protocol import EvidenceSession
from .schema import CaseFamily, CaseVariant, ToolObservation, load_case_family

__all__ = [
    "CaseFamily",
    "CaseVariant",
    "EvidenceSession",
    "ToolObservation",
    "analyze_trace",
    "compare_variants",
    "load_case_family",
    "validate_case_family",
]
