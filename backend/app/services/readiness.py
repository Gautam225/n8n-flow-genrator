"""Workflow review, readiness evaluation, and safe test planning service.

Provides deterministic static readiness assessments, credential verification status,
safe test plans separating local vs. instance-dependent checks, and non-mutating
static dry-run simulations.
"""
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from backend.app.schemas.ir import (
    KNOWN_LOOP_CONTROL_NODES,
    WorkflowIR,
    _is_trigger_node,
)
from backend.app.schemas.readiness import (
    CredentialReadinessItem,
    CredentialVerificationState,
    ExecutionTier,
    ReadinessCategory,
    ReadinessCheckItem,
    ReadinessItemStatus,
    ReadinessStatus,
    SafeSimulationResult,
    SafeTestPlan,
    SafeTestPlanStep,
    SideEffectRisk,
    SimulationNodeResult,
    WorkflowReadinessReport,
)
from backend.app.schemas.validation import ValidationIssueSeverity, ValidationReport
from backend.app.services.node_registry import NodeDefinition, NodeRegistry
from backend.app.services.validator import WorkflowValidator


# Statically classified node categories
LOCAL_STATIC_NODE_TYPES = {
    "n8n-nodes-base.code",
    "n8n-nodes-base.set",
    "n8n-nodes-base.if",
    "n8n-nodes-base.splitInBatches",
    "n8n-nodes-base.filter",
    "n8n-nodes-base.merge",
    "n8n-nodes-base.noOp",
    "n8n-nodes-base.manualTrigger",
    "n8n-nodes-base.dateTime",
    "n8n-nodes-base.compareDatasets",
    "n8n-nodes-base.switch",
    "n8n-nodes-base.aggregate",
}

MUTATING_OPERATIONS = {
    "create", "update", "delete", "post", "put", "patch", "send", "write", "insert", "append"
}


class WorkflowReadinessEvaluator:
    """Evaluates workflow readiness, credential states, and safe test execution plans."""

    def __init__(
        self,
        registry: Optional[NodeRegistry] = None,
        validator: Optional[WorkflowValidator] = None,
    ):
        self.registry = registry if registry is not None else NodeRegistry()
        self.validator = validator if validator is not None else WorkflowValidator(registry=self.registry)

    def evaluate(
        self,
        workflow: WorkflowIR,
        prompt_context: Optional[str] = None,
        available_n8n_credentials: Optional[List[Dict[str, Any]]] = None,
    ) -> WorkflowReadinessReport:
        """Performs a comprehensive readiness evaluation of the given WorkflowIR."""
        validation_report = self.validator.validate(workflow, prompt_context=prompt_context)
        checks: List[ReadinessCheckItem] = []
        credentials: List[CredentialReadinessItem] = []

        node_map = {n.id: n for n in workflow.nodes}

        # 1. Topology & Graph Integrity Checks
        self._evaluate_topology(workflow, validation_report, checks)

        # 2. Node Support & Schema Checks
        self._evaluate_nodes(workflow, validation_report, checks)

        # 3. Parameters Completeness Checks
        unresolved_config = self._evaluate_parameters(workflow, validation_report, checks)
        is_config_complete = len(unresolved_config) == 0

        # 4. Credential Verification Assessment (honest status, never claim verified without active n8n)
        self._evaluate_credentials(workflow, checks, credentials, available_n8n_credentials=available_n8n_credentials)
        has_missing_creds = any(c.verification_state == CredentialVerificationState.MISSING for c in credentials)
        has_invalid_creds = any(c.verification_state == CredentialVerificationState.INVALID for c in credentials)
        has_insecure_creds = any(c.verification_state == CredentialVerificationState.INSECURE_LITERAL for c in credentials)

        are_creds_configured = (
            len(credentials) == 0
            or (
                all(
                    c.verification_state in (
                        CredentialVerificationState.CONFIGURED,
                        CredentialVerificationState.VERIFIED,
                        CredentialVerificationState.REFERENCED,
                        CredentialVerificationState.UNVERIFIED_REFERENCE,
                        CredentialVerificationState.NOT_REQUIRED,
                    )
                    for c in credentials
                )
                and not has_missing_creds
                and not has_invalid_creds
                and not has_insecure_creds
            )
        )

        # 5. Build Safe Test Plan
        test_plan = self._build_test_plan(workflow, validation_report)

        # 6. Overall Readiness Calculation
        has_fatal = validation_report.has_fatal_errors or any(
            c.status == ReadinessItemStatus.FAIL and c.category in (ReadinessCategory.TOPOLOGY, ReadinessCategory.NODE_SUPPORT)
            for c in checks
        )
        has_warnings = (
            len(validation_report.warnings) > 0
            or any(c.status in (ReadinessItemStatus.WARNING, ReadinessItemStatus.FAIL) for c in checks)
            or not is_config_complete
        )

        is_structure_valid = validation_report.is_valid
        # Deployment ready strictly requires: valid structure, complete parameters, NO missing credentials, NO invalid credentials, NO insecure literal secrets
        is_deployment_ready = (
            is_structure_valid
            and is_config_complete
            and not has_missing_creds
            and not has_invalid_creds
            and not has_insecure_creds
            and len(workflow.nodes) > 0
        )

        if has_fatal:
            overall_status = ReadinessStatus.BLOCKED
            summary = (
                f"Workflow contains {len(validation_report.fatal_issues)} blocking error(s) that must be resolved "
                "before deployment or testing."
            )
        elif has_missing_creds:
            overall_status = ReadinessStatus.NEEDS_ATTENTION
            summary = (
                "Workflow structure is valid but required credentials are missing. "
                "Configure credential references in the node inspector before deploying."
            )
        elif has_invalid_creds:
            overall_status = ReadinessStatus.NEEDS_ATTENTION
            summary = (
                "Workflow references credential IDs not found in the connected n8n instance. "
                "Select existing credentials in the node inspector."
            )
        elif has_warnings or not is_config_complete:
            overall_status = ReadinessStatus.NEEDS_ATTENTION
            summary = (
                "Workflow structure is valid but requires configuration: missing parameters or unverified credentials "
                "need review prior to deployment."
            )
        else:
            overall_status = ReadinessStatus.READY
            summary = (
                "Workflow passed all static readiness checks and is ready for safe review and inactive n8n deployment."
            )

        return WorkflowReadinessReport(
            overall_status=overall_status,
            is_deployable_to_n8n=is_deployment_ready,
            is_structure_valid=is_structure_valid,
            is_configuration_complete=is_config_complete,
            are_credentials_configured=are_creds_configured,
            is_deployment_ready=is_deployment_ready,
            is_deployed=False,
            unresolved_configuration=unresolved_config,
            summary=summary,
            checks=checks,
            credentials=credentials,
            test_plan=test_plan,
            validation_report=validation_report,
        )

    def _evaluate_topology(
        self,
        workflow: WorkflowIR,
        report: ValidationReport,
        checks: List[ReadinessCheckItem],
    ) -> None:
        """Evaluates graph structure, triggers, and connectivity."""
        if not workflow.nodes:
            checks.append(
                ReadinessCheckItem(
                    category=ReadinessCategory.TOPOLOGY,
                    status=ReadinessItemStatus.FAIL,
                    title="Workflow is empty",
                    detail="The workflow contains zero nodes.",
                    actionable_recommendation="Add at least one trigger node to begin.",
                )
            )
            return

        # Check for trigger nodes
        triggers = [n for n in workflow.nodes if _is_trigger_node(n.node_type)]
        if not triggers:
            checks.append(
                ReadinessCheckItem(
                    category=ReadinessCategory.TOPOLOGY,
                    status=ReadinessItemStatus.WARNING,
                    title="No identifiable trigger node",
                    detail=(
                        "Workflow has no webhook, schedule, or manual trigger. "
                        "It can only be executed as a called sub-workflow in n8n."
                    ),
                    actionable_recommendation="Add a trigger node (e.g. manualTrigger or webhook) if this is a primary workflow.",
                )
            )
        else:
            checks.append(
                ReadinessCheckItem(
                    category=ReadinessCategory.TOPOLOGY,
                    status=ReadinessItemStatus.PASS,
                    title=f"Trigger configured ({len(triggers)})",
                    detail=f"Identified trigger: {', '.join(t.name for t in triggers)}.",
                    node_id=triggers[0].id,
                    node_name=triggers[0].name,
                )
            )

        # Check for disconnected / orphan nodes
        orphan_issues = [i for i in report.issues if i.rule_code == "ORPHAN_NODE"]
        if orphan_issues:
            for issue in orphan_issues:
                checks.append(
                    ReadinessCheckItem(
                        category=ReadinessCategory.TOPOLOGY,
                        status=ReadinessItemStatus.WARNING,
                        title="Disconnected Node",
                        detail=issue.message,
                        node_id=issue.node_id,
                        actionable_recommendation=issue.suggested_fix,
                    )
                )
        else:
            checks.append(
                ReadinessCheckItem(
                    category=ReadinessCategory.TOPOLOGY,
                    status=ReadinessItemStatus.PASS,
                    title="Graph connectivity complete",
                    detail="All nodes are connected to the workflow graph.",
                )
            )

        # Check for cycle / loop control
        cycle_issues = [
            i for i in report.issues if i.rule_code in ("UNCONTROLLED_CYCLE_DETECTED", "CONTROLLED_LOOP_DETECTED")
        ]
        if any(i.severity == ValidationIssueSeverity.FATAL for i in cycle_issues):
            fatal_cycle = next(i for i in cycle_issues if i.severity == ValidationIssueSeverity.FATAL)
            checks.append(
                ReadinessCheckItem(
                    category=ReadinessCategory.TOPOLOGY,
                    status=ReadinessItemStatus.FAIL,
                    title="Uncontrolled Cycle Detected",
                    detail=fatal_cycle.message,
                    actionable_recommendation=fatal_cycle.suggested_fix,
                )
            )
        else:
            checks.append(
                ReadinessCheckItem(
                    category=ReadinessCategory.TOPOLOGY,
                    status=ReadinessItemStatus.PASS,
                    title="DAG cycle policy satisfied",
                    detail="Graph contains no infinite recursion cycles.",
                )
            )

    def _evaluate_nodes(
        self,
        workflow: WorkflowIR,
        report: ValidationReport,
        checks: List[ReadinessCheckItem],
    ) -> None:
        """Evaluates node type existence and version compatibility."""
        unknown_nodes = [i for i in report.issues if i.rule_code == "NODE_TYPE_UNKNOWN"]
        if unknown_nodes:
            for issue in unknown_nodes:
                checks.append(
                    ReadinessCheckItem(
                        category=ReadinessCategory.NODE_SUPPORT,
                        status=ReadinessItemStatus.FAIL,
                        title="Unknown Node Type",
                        detail=issue.message,
                        node_id=issue.node_id,
                        actionable_recommendation=issue.suggested_fix,
                    )
                )
        else:
            checks.append(
                ReadinessCheckItem(
                    category=ReadinessCategory.NODE_SUPPORT,
                    status=ReadinessItemStatus.PASS,
                    title=f"All {len(workflow.nodes)} nodes recognized",
                    detail=f"All node types are cataloged in n8n {self.registry.provenance.get('n8n_version', '2.42.6')}.",
                )
            )

    def _evaluate_parameters(
        self,
        workflow: WorkflowIR,
        report: ValidationReport,
        checks: List[ReadinessCheckItem],
    ) -> List[str]:
        """Evaluates required parameters, types, options, and placeholders.

        Returns a list of unconfigured parameter error strings.
        """
        unresolved_params: List[str] = []
        missing_params = [i for i in report.issues if i.rule_code == "MISSING_REQUIRED_PARAMETER"]
        invalid_types = [i for i in report.issues if i.rule_code in ("INVALID_PARAMETER_TYPE", "INVALID_PARAMETER_OPTION")]

        for issue in missing_params:
            unresolved_params.append(issue.message)
            checks.append(
                ReadinessCheckItem(
                    category=ReadinessCategory.PARAMETERS,
                    status=ReadinessItemStatus.FAIL,
                    title="Missing Required Parameter",
                    detail=issue.message,
                    node_id=issue.node_id,
                    actionable_recommendation=issue.suggested_fix,
                )
            )

        for issue in invalid_types:
            unresolved_params.append(issue.message)
            checks.append(
                ReadinessCheckItem(
                    category=ReadinessCategory.PARAMETERS,
                    status=ReadinessItemStatus.FAIL,
                    title="Invalid Parameter Value",
                    detail=issue.message,
                    node_id=issue.node_id,
                    actionable_recommendation=issue.suggested_fix,
                )
            )

        # Check for unconfigured placeholders like <YOUR_TELEGRAM_CHAT_ID> or <YOUR_SPREADSHEET_ID>
        for node in workflow.nodes:
            params = node.parameters or {}
            for k, v in params.items():
                if isinstance(v, str):
                    clean_v = v.strip()
                    if "<YOUR_" in clean_v:
                        msg = f"Node '{node.name}' parameter '{k}' has unconfigured placeholder '{clean_v}'."
                        unresolved_params.append(msg)
                        checks.append(
                            ReadinessCheckItem(
                                category=ReadinessCategory.PARAMETERS,
                                status=ReadinessItemStatus.WARNING,
                                title=f"Unconfigured Parameter '{k}'",
                                detail=msg,
                                node_id=node.id,
                                node_name=node.name,
                                actionable_recommendation=f"Open Node Inspector and configure real value for '{k}'.",
                            )
                        )

            # Node-specific checks for common integrations
            if "googlesheetstrigger" in node.node_type.lower():
                doc_id = params.get("documentId")
                if not doc_id or "<YOUR_" in str(doc_id):
                    msg = f"Google Sheets Trigger '{node.name}' is missing Spreadsheet / Document ID."
                    if msg not in unresolved_params:
                        unresolved_params.append(msg)
                        checks.append(
                            ReadinessCheckItem(
                                category=ReadinessCategory.PARAMETERS,
                                status=ReadinessItemStatus.FAIL,
                                title="Missing Google Sheets Document ID",
                                detail=msg,
                                node_id=node.id,
                                node_name=node.name,
                                actionable_recommendation="Provide the spreadsheet ID from your Google Sheets URL in the Node Inspector.",
                            )
                        )
                sheet_name = params.get("sheetName")
                if not sheet_name or "<YOUR_" in str(sheet_name):
                    msg = f"Google Sheets Trigger '{node.name}' is missing Sheet Name (e.g. 'Sheet1')."
                    if msg not in unresolved_params:
                        unresolved_params.append(msg)
                        checks.append(
                            ReadinessCheckItem(
                                category=ReadinessCategory.PARAMETERS,
                                status=ReadinessItemStatus.FAIL,
                                title="Missing Google Sheets Sheet Name",
                                detail=msg,
                                node_id=node.id,
                                node_name=node.name,
                                actionable_recommendation="Specify the tab name (e.g. 'Sheet1') in the Node Inspector.",
                            )
                        )

            elif "telegram" in node.node_type.lower():
                chat_id = params.get("chatId")
                if not chat_id or "<YOUR_" in str(chat_id) or str(chat_id) in ("private_chat", "group", "channel"):
                    msg = f"Telegram node '{node.name}' is missing a real Telegram Chat ID."
                    if msg not in unresolved_params:
                        unresolved_params.append(msg)
                        checks.append(
                            ReadinessCheckItem(
                                category=ReadinessCategory.PARAMETERS,
                                status=ReadinessItemStatus.FAIL,
                                title="Missing Telegram Chat ID",
                                detail=msg,
                                node_id=node.id,
                                node_name=node.name,
                                actionable_recommendation="Enter your numeric Telegram Chat ID or public channel username in the Node Inspector.",
                            )
                        )

        if not unresolved_params:
            checks.append(
                ReadinessCheckItem(
                    category=ReadinessCategory.PARAMETERS,
                    status=ReadinessItemStatus.PASS,
                    title="Required parameters complete",
                    detail="All mandatory parameters have valid values without placeholder markers.",
                )
            )

        return unresolved_params

    def _evaluate_credentials(
        self,
        workflow: WorkflowIR,
        checks: List[ReadinessCheckItem],
        credentials: List[CredentialReadinessItem],
        available_n8n_credentials: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Evaluates credential configurations honestly distinguishing missing, referenced, configured, verified, and invalid."""
        total_required_creds = 0
        missing_creds = 0

        # Index available credentials from connected n8n by type
        n8n_creds_by_type: Dict[str, List[Dict[str, Any]]] = {}
        if available_n8n_credentials:
            for ac in available_n8n_credentials:
                ctype = str(ac.get("type", ""))
                if ctype:
                    n8n_creds_by_type.setdefault(ctype, []).append(ac)

        for node in workflow.nodes:
            node_def = self.registry.get_node(node.node_type)
            if not node_def:
                continue

            expected_creds = node_def.get_expected_credentials(node.parameters, node.credentials)
            for cred_spec in expected_creds:
                total_required_creds += 1 if cred_spec.required else 0
                has_cred = bool(node.credentials and cred_spec.name in node.credentials)
                cred_val = node.credentials.get(cred_spec.name) if node.credentials else None

                # Format human readable name for guidance
                cred_display = cred_spec.name
                if "googleSheetsTrigger" in cred_spec.name:
                    cred_display = "Google Sheets Trigger OAuth2 API"
                elif "googleSheets" in cred_spec.name:
                    cred_display = "Google Sheets OAuth2 API"
                elif "telegram" in cred_spec.name:
                    cred_display = "Telegram API"

                if not has_cred or cred_val is None:
                    if cred_spec.required:
                        missing_creds += 1
                        credentials.append(
                            CredentialReadinessItem(
                                node_id=node.id,
                                node_name=node.name,
                                credential_type=cred_spec.name,
                                is_required=True,
                                configured_reference=None,
                                verification_state=CredentialVerificationState.MISSING,
                                guidance=(
                                    f"Node requires '{cred_spec.name}'. In n8n, navigate to "
                                    f"Credentials → New Credential → '{cred_display}' to configure it."
                                ),
                            )
                        )
                else:
                    # Check for plaintext secret embedding
                    raw_secret_keys = {"password", "secret", "apikey", "api_key", "token", "private_key", "auth_token"}
                    is_literal = isinstance(cred_val, dict) and any(
                        k.lower() in raw_secret_keys for k in cred_val.keys()
                    )

                    ref_id = str(cred_val.get("id", "")) if isinstance(cred_val, dict) else str(cred_val)
                    ref_name = str(cred_val.get("name", "")) if isinstance(cred_val, dict) else ""
                    ref_display = f"ID: {ref_id}" if ref_id else (ref_name or "logical reference")

                    if is_literal:
                        credentials.append(
                            CredentialReadinessItem(
                                node_id=node.id,
                                node_name=node.name,
                                credential_type=cred_spec.name,
                                is_required=cred_spec.required,
                                configured_reference=ref_display,
                                verification_state=CredentialVerificationState.INSECURE_LITERAL,
                                guidance="Replace embedded plaintext secrets with an indirect credential ID reference.",
                            )
                        )
                    elif available_n8n_credentials is not None:
                        matching_n8n_creds = n8n_creds_by_type.get(cred_spec.name, [])
                        matched_by_id = [c for c in matching_n8n_creds if str(c.get("id")) == ref_id] if ref_id else []

                        if matched_by_id:
                            matched_cred = matched_by_id[0]
                            credentials.append(
                                CredentialReadinessItem(
                                    node_id=node.id,
                                    node_name=node.name,
                                    credential_type=cred_spec.name,
                                    is_required=cred_spec.required,
                                    configured_reference=f"ID: {ref_id} ({matched_cred.get('name', ref_name)})",
                                    verification_state=CredentialVerificationState.CONFIGURED,
                                    guidance=(
                                        f"Matching credential '{matched_cred.get('name')}' (ID: {ref_id}) "
                                        f"verified in connected n8n instance."
                                    ),
                                )
                            )
                        elif ref_id and matching_n8n_creds and not matched_by_id:
                            credentials.append(
                                CredentialReadinessItem(
                                    node_id=node.id,
                                    node_name=node.name,
                                    credential_type=cred_spec.name,
                                    is_required=cred_spec.required,
                                    configured_reference=ref_display,
                                    verification_state=CredentialVerificationState.INVALID,
                                    guidance=(
                                        f"Referenced credential ID '{ref_id}' does not exist in target n8n. "
                                        f"Select an existing '{cred_display}' from n8n or update the reference."
                                    ),
                                )
                            )
                        else:
                            credentials.append(
                                CredentialReadinessItem(
                                    node_id=node.id,
                                    node_name=node.name,
                                    credential_type=cred_spec.name,
                                    is_required=cred_spec.required,
                                    configured_reference=ref_display,
                                    verification_state=CredentialVerificationState.REFERENCED,
                                    guidance=(
                                        f"Logical reference configured. Create '{cred_display}' in target n8n "
                                        f"to complete configuration."
                                    ),
                                )
                            )
                    else:
                        credentials.append(
                            CredentialReadinessItem(
                                node_id=node.id,
                                node_name=node.name,
                                credential_type=cred_spec.name,
                                is_required=cred_spec.required,
                                configured_reference=ref_display,
                                verification_state=CredentialVerificationState.UNVERIFIED_REFERENCE,
                                guidance=(
                                    "Logical credential reference configured. Validity can only be verified "
                                    "against an authenticated, active n8n instance containing this credential."
                                ),
                            )
                        )

        # High-level credential check summary
        if missing_creds > 0:
            checks.append(
                ReadinessCheckItem(
                    category=ReadinessCategory.CREDENTIALS,
                    status=ReadinessItemStatus.WARNING,
                    title=f"Unresolved Credentials ({missing_creds})",
                    detail=f"{missing_creds} node(s) require credential references that have not been assigned.",
                    actionable_recommendation="Assign credential references to affected nodes in the node inspector.",
                )
            )
        elif any(c.verification_state == CredentialVerificationState.INVALID for c in credentials):
            checks.append(
                ReadinessCheckItem(
                    category=ReadinessCategory.CREDENTIALS,
                    status=ReadinessItemStatus.WARNING,
                    title="Invalid Credential Reference(s)",
                    detail="One or more credential references point to IDs not found in connected n8n.",
                    actionable_recommendation="Select valid credentials in the node inspector.",
                )
            )
        elif any(c.verification_state == CredentialVerificationState.CONFIGURED for c in credentials):
            configured_count = sum(1 for c in credentials if c.verification_state == CredentialVerificationState.CONFIGURED)
            checks.append(
                ReadinessCheckItem(
                    category=ReadinessCategory.CREDENTIALS,
                    status=ReadinessItemStatus.PASS,
                    title=f"Credentials Configured ({configured_count}/{len(credentials)})",
                    detail=f"{configured_count} credential reference(s) successfully matched in target n8n.",
                    actionable_recommendation="Credentials exist in n8n. Ready for deployment.",
                )
            )
        elif credentials:
            checks.append(
                ReadinessCheckItem(
                    category=ReadinessCategory.CREDENTIALS,
                    status=ReadinessItemStatus.INFO,
                    title="Credentials Pending Live Instance Verification",
                    detail=(
                        f"{len(credentials)} credential reference(s) mapped. In accordance with zero-trust safety, "
                        "credentials cannot be claimed verified without an active n8n instance authentication check."
                    ),
                    actionable_recommendation="Ensure corresponding credentials exist in target n8n before activating.",
                )
            )
        else:
            checks.append(
                ReadinessCheckItem(
                    category=ReadinessCategory.CREDENTIALS,
                    status=ReadinessItemStatus.PASS,
                    title="No external credentials required",
                    detail="This workflow operates solely on internal logic and requires no external API credentials.",
                )
            )

    def _build_test_plan(
        self,
        workflow: WorkflowIR,
        report: ValidationReport,
    ) -> SafeTestPlan:
        """Generates a safe test execution plan identifying local vs. instance-dependent checks."""
        steps: List[SafeTestPlanStep] = []
        local_checks: List[str] = [
            "Pydantic schema structure and Tarjan cycle verification",
            "Node registry type existence and version compatibility",
            "Mandatory parameter presence and primitive type bounds",
            "Handle socket index bounds (output-0, output-1, error)",
            "Deterministic native n8n compilation format",
            "DAG execution ordering and mock payload simulation",
        ]
        instance_checks: List[str] = [
            "n8n REST API connectivity & version handshake",
            "Credential existence and authorization scopes inside n8n credential vault",
            "Webhook trigger path registration and endpoint reachability",
            "Third-party external API live response schema validation",
        ]

        # Topologically sort nodes for execution plan
        sorted_nodes = self._topological_sort(workflow)

        for idx, node in enumerate(sorted_nodes, start=1):
            is_local = node.node_type in LOCAL_STATIC_NODE_TYPES
            node_def = self.registry.get_node(node.node_type)

            # Determine side effect risk
            operation = (node.operation or "").lower()
            if any(m in operation for m in MUTATING_OPERATIONS):
                side_effect = SideEffectRisk.EXTERNAL_MUTATION
            elif "get" in operation or "fetch" in operation or "read" in operation:
                side_effect = SideEffectRisk.READ_ONLY
            elif is_local:
                side_effect = SideEffectRisk.NONE
            else:
                side_effect = SideEffectRisk.READ_ONLY

            # Prerequisites
            prereqs: List[str] = []
            if _is_trigger_node(node.node_type):
                prereqs.append("Sample trigger input payload")
            if node_def and node_def.credentials:
                prereqs.append(f"Requires valid {', '.join(c.name for c in node_def.credentials)} in n8n")
            if not is_local:
                prereqs.append("Active network connectivity to target service")

            steps.append(
                SafeTestPlanStep(
                    step_number=idx,
                    node_id=node.id,
                    node_name=node.name,
                    node_type=node.node_type,
                    execution_tier=ExecutionTier.LOCAL_STATIC if is_local else ExecutionTier.REQUIRES_N8N,
                    testable_locally=is_local,
                    prerequisites=prereqs,
                    side_effect_risk=side_effect,
                )
            )

        return SafeTestPlan(
            can_run_local_dry_run=not report.has_fatal_errors and len(workflow.nodes) > 0,
            steps=steps,
            local_checks=local_checks,
            instance_dependent_checks=instance_checks,
        )

    def _topological_sort(self, workflow: WorkflowIR) -> List[Any]:
        """Returns nodes in topological dependency order (falling back to declaration order on cycles)."""
        node_map = {n.id: n for n in workflow.nodes}
        in_degree: Dict[str, int] = {n.id: 0 for n in workflow.nodes}
        adj: Dict[str, List[str]] = defaultdict(list)

        for edge in workflow.edges:
            if edge.source_id in node_map and edge.target_id in node_map:
                adj[edge.source_id].append(edge.target_id)
                in_degree[edge.target_id] += 1

        queue = deque([n.id for n in workflow.nodes if in_degree[n.id] == 0])
        ordered_ids: List[str] = []

        while queue:
            curr = queue.popleft()
            ordered_ids.append(curr)
            for neighbor in adj[curr]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # If cycles prevented all nodes from being placed, append remaining nodes
        remaining = [n.id for n in workflow.nodes if n.id not in ordered_ids]
        ordered_ids.extend(remaining)

        return [node_map[nid] for nid in ordered_ids]

    def simulate_dry_run(self, workflow: WorkflowIR) -> SafeSimulationResult:
        """Executes a safe, non-mutating, deterministic static simulation of the workflow DAG."""
        validation_report = self.validator.validate(workflow)
        fatal_node_ids = {i.node_id for i in validation_report.fatal_issues if i.node_id}

        sorted_nodes = self._topological_sort(workflow)
        results: List[SimulationNodeResult] = []
        passed_count = 0

        for node in sorted_nodes:
            if node.id in fatal_node_ids:
                results.append(
                    SimulationNodeResult(
                        node_id=node.id,
                        node_name=node.name,
                        status="blocked",
                        summary=f"Execution blocked: Node '{node.name}' has unresolved fatal validation errors.",
                        sample_output_keys=[],
                    )
                )
                continue

            # Produce sample simulated output shape depending on node type
            if _is_trigger_node(node.node_type):
                sample_keys = ["headers", "body", "query", "timestamp"]
                summary = f"Simulated trigger emission: Generated mock event payload ({len(sample_keys)} attributes)."
            elif node.node_type == "n8n-nodes-base.if":
                sample_keys = ["condition_evaluated", "branch_matched", "data"]
                summary = "Simulated conditional branch evaluation based on mock input."
            elif node.node_type == "n8n-nodes-base.set":
                param_keys = list((node.parameters or {}).keys())
                sample_keys = param_keys if param_keys else ["data", "status"]
                summary = f"Simulated state assignment: Applied {len(sample_keys)} parameter assignments."
            elif node.node_type in LOCAL_STATIC_NODE_TYPES:
                sample_keys = ["output", "execution_index", "success"]
                summary = f"Simulated local transformation step '{node.name}' with mock data items."
            else:
                sample_keys = ["mock_response", "status_code", "data"]
                summary = (
                    f"Simulated boundary interface for '{node.name}' ({node.node_type}). "
                    "External network request was skipped per safety policy."
                )

            passed_count += 1
            results.append(
                SimulationNodeResult(
                    node_id=node.id,
                    node_name=node.name,
                    status="simulated_success",
                    summary=summary,
                    sample_output_keys=sample_keys,
                )
            )

        success = passed_count == len(sorted_nodes) and not validation_report.has_fatal_errors

        return SafeSimulationResult(
            success=success,
            execution_type="deterministic_static_dry_run",
            total_nodes=len(sorted_nodes),
            passed_nodes=passed_count,
            node_results=results,
        )


def evaluate_readiness(
    workflow: WorkflowIR,
    registry: Optional[NodeRegistry] = None,
) -> WorkflowReadinessReport:
    """Convenience functional entrypoint for workflow readiness assessment."""
    evaluator = WorkflowReadinessEvaluator(registry=registry)
    return evaluator.evaluate(workflow)
