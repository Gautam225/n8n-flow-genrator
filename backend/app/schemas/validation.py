"""Validation schemas and report contracts for workflow evaluation."""
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ValidationIssueSeverity(str, Enum):
    """Severity classification for workflow validation issues."""
    FATAL = "fatal"
    WARNING = "warning"
    INFO = "info"


class ValidationIssue(BaseModel):
    """Represents a discrete structural or semantic problem in a workflow."""
    model_config = ConfigDict(frozen=True)

    severity: ValidationIssueSeverity
    rule_code: str = Field(description="Machine-readable rule identifier, e.g. 'DUPLICATE_NODE_ID'")
    message: str = Field(description="Human-readable description of the problem")
    node_id: Optional[str] = Field(default=None, description="Affected node ID, if applicable")
    edge_source_id: Optional[str] = Field(default=None, description="Edge source node ID, if applicable")
    edge_target_id: Optional[str] = Field(default=None, description="Edge target node ID, if applicable")
    category: Optional[str] = Field(
        default=None,
        description="Actionable category (e.g. unknown_node_type, unsupported_operation, missing_required_config, invalid_parameter, invalid_connection, unresolved_data_mapping, unsupported_structure, credential_unverified, external_access_untested)",
    )
    property_path: Optional[str] = Field(default=None, description="Dotted property path if parameter-specific")
    suggested_fix: Optional[str] = Field(default=None, description="Actionable recommendation to repair the issue")

    @property
    def resolved_category(self) -> str:
        """Returns explicit category or deterministically resolves it from rule_code."""
        if self.category:
            return self.category
        code = self.rule_code.upper()
        if any(k in code for k in ("UNKNOWN_NODE", "NODE_TYPE_UNKNOWN", "FATAL_RESTRICTED")):
            return "unknown_node_type"
        if any(k in code for k in ("OPERATION_UNSUPPORTED", "UNSUPPORTED_PARAMETER", "UNSUPPORTED_VERSION")):
            return "unsupported_operation"
        if any(k in code for k in ("MISSING_REQUIRED_PARAMETER", "MISSING_REQUIRED_CONFIG")):
            return "missing_required_config"
        if any(k in code for k in ("INVALID_PARAMETER", "FABRICATED_PLACEHOLDER", "RESTRICTED_CODE")):
            return "invalid_parameter"
        if any(k in code for k in ("CONNECTION", "EDGE", "CYCLE", "SOCKET", "OUTPUT_INDEX", "ORPHAN", "MULTIPLE_TRIGGERS")):
            return "invalid_connection"
        if any(k in code for k in ("DATA_FLOW", "UNMAPPED", "MAPPING", "FIELD")):
            return "unresolved_data_mapping"
        if any(k in code for k in ("STRUCTURE", "LOOP", "TOPOLOGY")):
            return "unsupported_structure"
        if any(k in code for k in ("CREDENTIAL", "SECRET")):
            return "credential_unverified"
        return "general_validation"


class ValidationReport(BaseModel):
    """Comprehensive report returned by workflow structural and schema validators."""
    model_config = ConfigDict(validate_assignment=True)

    is_valid: bool = Field(description="True if no FATAL severity issues exist")
    issues: List[ValidationIssue] = Field(default_factory=list)
    checks_skipped: bool = Field(
        default=False,
        description="True if any validation checks were skipped due to missing/dynamic schema definitions"
    )

    @property
    def has_fatal_errors(self) -> bool:
        """Returns True if any issue has severity FATAL."""
        return any(issue.severity == ValidationIssueSeverity.FATAL for issue in self.issues)

    @property
    def fatal_issues(self) -> List[ValidationIssue]:
        """Returns all fatal issues that block workflow execution."""
        return [issue for issue in self.issues if issue.severity == ValidationIssueSeverity.FATAL]

    @property
    def warnings(self) -> List[ValidationIssue]:
        """Returns all warning issues."""
        return [issue for issue in self.issues if issue.severity == ValidationIssueSeverity.WARNING]

    @property
    def infos(self) -> List[ValidationIssue]:
        """Returns all informational issues."""
        return [issue for issue in self.issues if issue.severity == ValidationIssueSeverity.INFO]

    def add_issue(self, issue: ValidationIssue) -> None:
        """Appends a new issue and recalculates is_valid status."""
        self.issues.append(issue)
        if issue.severity == ValidationIssueSeverity.FATAL:
            self.is_valid = False
