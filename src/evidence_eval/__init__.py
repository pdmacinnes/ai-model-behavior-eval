"""Evidence-bounded debugging behavior study primitives."""

from .analysis import analyze_trace, compare_variants
from .behavior_report import (
    BEHAVIOR_REPORT_SCHEMA,
    BehaviorReportError,
    build_behavior_report,
    build_run_narrative,
)
from .calibration import calibrate_case_family
from .case_validation import validate_case_family
from .execution_policy import (
    APPROVED_PROVIDER_ADAPTER_ID,
    ExecutionPolicyError,
    NETWORK_AUTHORIZATION_ENV,
    PROVIDER_CREDENTIAL_ENV,
    live_environment_names,
    validate_execution_authorization,
    validate_trusted_provider_command,
)
from .protocol import EvidenceSession
from .public import (
    derive_public_pair_id,
    derive_public_run_id,
    sanitize_public_batch_manifest,
    sanitize_public_run,
    sanitize_public_trace,
    sanitize_public_verifier_result,
)
from .pilot import (
    PILOT_BATCH_MANIFEST_SCHEMA,
    PILOT_REGISTRATION_SCHEMA,
    PilotCondition,
    PilotRegistration,
    PilotRegistrationError,
    load_pilot_registration,
    plan_pilot_trials,
    run_pilot_batch,
)
from .runner import AgentResult, EvidenceTools, ModelCondition, run_unattended_trial, tool_contract
from .schema import CaseFamily, CaseVariant, ToolObservation, load_case_family
from .subprocess_adapter import SubprocessAdapterConfig, SubprocessWorkspaceAdapter
from .provider_worker import (
    OpenAICompatibleTransport,
    ProviderReply,
    ProviderToolCall,
    ProviderTransportError,
    ScriptedMockTransport,
    build_openai_compatible_request,
    parse_openai_compatible_response,
    run_provider_worker,
)
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
    "BEHAVIOR_REPORT_SCHEMA",
    "BehaviorReportError",
    "build_behavior_report",
    "build_run_narrative",
    "calibrate_case_family",
    "compare_variants",
    "run_unattended_trial",
    "sanitize_public_run",
    "sanitize_public_trace",
    "sanitize_public_batch_manifest",
    "sanitize_public_verifier_result",
    "derive_public_run_id",
    "derive_public_pair_id",
    "PILOT_BATCH_MANIFEST_SCHEMA",
    "PILOT_REGISTRATION_SCHEMA",
    "PilotCondition",
    "PilotRegistration",
    "PilotRegistrationError",
    "load_pilot_registration",
    "plan_pilot_trials",
    "run_pilot_batch",
    "tool_contract",
    "load_case_family",
    "validate_case_family",
    "APPROVED_PROVIDER_ADAPTER_ID",
    "ExecutionPolicyError",
    "NETWORK_AUTHORIZATION_ENV",
    "PROVIDER_CREDENTIAL_ENV",
    "live_environment_names",
    "validate_execution_authorization",
    "validate_trusted_provider_command",
    "SubprocessAdapterConfig",
    "SubprocessWorkspaceAdapter",
    "OpenAICompatibleTransport",
    "ProviderReply",
    "ProviderToolCall",
    "ProviderTransportError",
    "ScriptedMockTransport",
    "build_openai_compatible_request",
    "parse_openai_compatible_response",
    "run_provider_worker",
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
