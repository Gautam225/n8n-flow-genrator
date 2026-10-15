"""Readiness evaluation and safe test planning schemas."""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field

from backend.app.schemas.validation import ValidationReport


class ReadinessStatus(str, Enum):
    """Overall workflow readiness status."""
    READY = "ready"
    NEEDS_ATTENTION = "needs_attention"
    BLOCKED = "blocked"


class ReadinessCategory(str, Enum):
    """Category classification for readiness check items."""
    TOPOLOGY = "topology"
    PARAMETERS = "parameters"
    CREDENTIALS = "credentials"
    NODE_SUPPORT = "node_support"
    EXECUTION_SAFETY = "execution_safety"


class ReadinessItemStatus(str, Enum):
    """Result status for a discrete readiness check."""
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    INFO = "info"


class CredentialVerificationState(str, Enum):
    """Honest credential state tracking distinguishing missing, referenced, configured, verified, and invalid."""
    MISSING = "missing"
    REFERENCED = "referenced"
    UNVERIFIED_REFERENCE = "unverified_reference"
    CONFIGURED = "configured"
    VERIFIED = "verified"
    INVALID = "invalid"
    INSECURE_LITERAL = "insecure_literal"
    NOT_REQUIRED = "not_required"


class ExecutionTier(str, Enum):
    """Execution tier indicating where a node step can be tested."""
    LOCAL_STATIC = "local_static"
    REQUIRES_N8N = "requires_n8n"
    REQUIRES_EXTERNAL_SERVICE = "requires_external_service"


class SideEffectRisk(str, Enum):
    """Side effect risk classification for node types."""
    NONE = "none"
    READ_ONLY = "read_only"
    EXTERNAL_MUTATION = "external_mutation"


class ReadinessCheckItem(BaseModel):
    """A discrete verifiable check evaluated for workflow readiness."""
    model_config = ConfigDict(frozen=True)

    category: ReadinessCategory
    status: ReadinessItemStatus
    title: str
    detail: str
    node_id: Optional[str] = None
    node_name: Optional[str] = None
    actionable_recommendation: Optional[str] = None


class CredentialReadinessItem(BaseModel):
    """Verifiable credential requirement and configuration state."""
    model_config = ConfigDict(frozen=True)

    node_id: str
    node_name: str
    credential_type: str
    is_required: bool
    configured_reference: Optional[str] = None
    verification_state: CredentialVerificationState
    guidance: str


class SafeTestPlanStep(BaseModel):
    """An execution step in the safe test plan."""
    model_config = ConfigDict(frozen=True)

    step_number: int
    node_id: str
    node_name: str
    node_type: str
    execution_tier: ExecutionTier
    testable_locally: bool
    prerequisites: List[str] = Field(default_factory=list)
    side_effect_risk: SideEffectRisk


class SafeTestPlan(BaseModel):
    """Safe test execution plan separating local static checks from target-dependent checks."""
    model_config = ConfigDict(frozen=True)

    can_run_local_dry_run: bool
    steps: List[SafeTestPlanStep] = Field(default_factory=list)
    local_checks: List[str] = Field(default_factory=list)
    instance_dependent_checks: List[str] = Field(default_factory=list)


class SimulationNodeResult(BaseModel):
    """Step result from a deterministic static simulation."""
    model_config = ConfigDict(frozen=True)

    node_id: str
    node_name: str
    status: str  # "simulated_success" | "blocked" | "warning"
    summary: str
    sample_output_keys: List[str] = Field(default_factory=list)


class SafeSimulationResult(BaseModel):
    """Deterministic static dry-run simulation result with non-mutating guarantee."""
    model_config = ConfigDict(frozen=True)

    success: bool
    execution_type: str = "deterministic_static_dry_run"
    disclaimer: str = (
        "This dry-run performed static data-flow and parameter completeness verification only. "
        "No external services, network sockets, or n8n instance mutations were executed."
    )
    total_nodes: int
    passed_nodes: int
    node_results: List[SimulationNodeResult] = Field(default_factory=list)
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class WorkflowReadinessReport(BaseModel):
    """Complete workflow review and readiness evaluation report separating distinct quality gates."""
    model_config = ConfigDict(validate_assignment=True)

    overall_status: ReadinessStatus
    is_deployable_to_n8n: bool
    is_structure_valid: bool = True
    is_configuration_complete: bool = True
    are_credentials_configured: bool = False
    is_deployment_ready: bool = False
    is_deployed: bool = False
    unresolved_configuration: List[str] = Field(default_factory=list)
    summary: str
    checks: List[ReadinessCheckItem] = Field(default_factory=list)
    credentials: List[CredentialReadinessItem] = Field(default_factory=list)
    test_plan: SafeTestPlan
    validation_report: ValidationReport
