"""Schema-aware workflow validation engine.

Combines structural graph validation (DAG topology, loop classifications, input/output
socket integrity) with deep node-registry schema checks (node type existence, version
compatibility, required parameters, parameter enum options, type checking, and credential
reference security).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from backend.app.schemas.ir import (
    KNOWN_LOOP_CONTROL_NODES,
    KNOWN_NODE_OUTPUT_COUNTS,
    WorkflowIR,
    _detect_cycles_tarjan,
    _is_trigger_node,
    validate_workflow_ir,
)
from backend.app.schemas.validation import (
    ValidationIssue,
    ValidationIssueSeverity,
    ValidationReport,
)
from backend.app.services.node_registry import NodeDefinition, NodeRegistry

RESTRICTED_NODE_TYPES_NORMALIZED: Set[str] = {
    "n8n-nodes-base.executecommand",
    "executecommand",
    "n8n-nodes-base.ssh",
    "ssh",
    "n8n-nodes-base.localfileaccess",
    "localfileaccess",
    "n8n-nodes-base.readwritefiles",
    "readwritefiles",
}

RESTRICTED_CODE_PATTERNS: List[Tuple[str, str]] = [
    (r"\bchild_process\b", "child_process execution"),
    (r"\bfs\b|\bfs\.", "direct filesystem access"),
    (r"\beval\s*\(", "dynamic eval execution"),
    (r"\bFunction\s*\(", "dynamic Function constructor execution"),
    (r"\bprocess\.exit\b", "process.exit invocation"),
    (r"\b(globalThis|global)\.process\b", "global process access"),
    (r"\b__import__\b", "dynamic __import__ invocation"),
    (r"\bimportlib\b", "dynamic importlib module loading"),
    (r"\bsubprocess\b", "subprocess execution"),
    (r"\bos\.system\b", "os.system shell execution"),
    (r"\bos\.popen\b", "os.popen shell execution"),
    (r"\bopen\s*\(", "direct filesystem open() call"),
    (r"\bpty\b", "pty pseudo-terminal spawn"),
]


def is_property_visible(display_options: Optional[Dict[str, Any]], parameters: Dict[str, Any]) -> bool:
    """Evaluates n8n displayOptions show/hide rules against currently configured parameters."""
    if not display_options:
        return True

    show_rules = display_options.get("show")
    if show_rules and isinstance(show_rules, dict):
        for key, expected_vals in show_rules.items():
            param_val = parameters.get(key)
            if isinstance(expected_vals, list):
                if param_val not in expected_vals:
                    return False
            else:
                if param_val != expected_vals:
                    return False

    hide_rules = display_options.get("hide")
    if hide_rules and isinstance(hide_rules, dict):
        hidden = True
        for key, expected_vals in hide_rules.items():
            param_val = parameters.get(key)
            if isinstance(expected_vals, list):
                if param_val not in expected_vals:
                    hidden = False
                    break
            else:
                if param_val != expected_vals:
                    hidden = False
                    break
        if hidden:
            return False

    return True


class WorkflowValidator:
    """Validator performing comprehensive structural and schema-aware workflow analysis."""

    def __init__(self, registry: Optional[NodeRegistry] = None):
        """Initializes validator with optional custom or default node registry."""
        self.registry = registry if registry is not None else NodeRegistry()

    def validate(
        self,
        workflow: WorkflowIR,
        prompt_context: Optional[str] = None,
        intent: Optional[Any] = None,
    ) -> ValidationReport:
        """Validates a WorkflowIR against structural rules, installed node schemas, and semantic intent.

        Returns a detailed ValidationReport containing fatal errors, warnings,
        informational notes, and records whether any checks were skipped due to
        incomplete or dynamic schemas.
        """
        # 1. Run baseline structural validation from schemas.ir
        report = validate_workflow_ir(workflow)

        if not workflow.nodes:
            return report

        node_map = {n.id: n for n in workflow.nodes}

        # 2. Check for unique node display names (required by n8n connection system)
        seen_names: Dict[str, str] = {}
        for node in workflow.nodes:
            if node.name in seen_names:
                report.add_issue(
                    ValidationIssue(
                        severity=ValidationIssueSeverity.FATAL,
                        rule_code="DUPLICATE_NODE_NAME",
                        node_id=node.id,
                        message=(
                            f"Node display name '{node.name}' is already used by node '{seen_names[node.name]}'. "
                            "In n8n, all node display names must be unique because connections reference nodes by name."
                        ),
                        suggested_fix="Assign a unique display name to each node in the workflow."
                    )
                )
            else:
                seen_names[node.name] = node.id

        # 3. Node-Registry-Aware Schema Validation
        for node in workflow.nodes:
            self._validate_node_schema(node, workflow, report)

        # 4. Semantic Intent and Graph Consistency Validation
        self._validate_semantic_consistency(workflow, prompt_context, intent, report)

        return report

    def _validate_node_schema(
        self,
        node: Any,
        workflow: WorkflowIR,
        report: ValidationReport
    ) -> None:
        """Validates an individual node against its registered schema."""
        # Tier 3 Restricted Node Check (Arbitrary execution / local filesystem risks)
        node_type_norm = node.node_type.strip().lower()
        if (
            node_type_norm in RESTRICTED_NODE_TYPES_NORMALIZED
            or (node_type_norm.startswith("n8n-nodes-base.") and node_type_norm[len("n8n-nodes-base."):] in RESTRICTED_NODE_TYPES_NORMALIZED)
        ):
            report.add_issue(
                ValidationIssue(
                    severity=ValidationIssueSeverity.FATAL,
                    rule_code="FATAL_RESTRICTED_NODE",
                    node_id=node.id,
                    message=(
                        f"Node '{node.name}' uses restricted node type '{node.node_type}'. "
                        "Host command execution, SSH, and direct local filesystem access are blocked by policy."
                    ),
                    suggested_fix="Remove the restricted node or replace with a supported safe API/HTTP node."
                )
            )
            return

        # Code Node Sandboxing / Dangerous Pattern Check
        is_code_node = (
            node_type_norm in ("n8n-nodes-base.code", "code")
            or node_type_norm.endswith(".code")
        )
        if is_code_node:
            def _decode_escapes(text: str) -> str:
                def _hex_repl(m: re.Match) -> str:
                    try:
                        return chr(int(m.group(1), 16))
                    except Exception:
                        return m.group(0)

                def _uni_repl(m: re.Match) -> str:
                    try:
                        return chr(int(m.group(1), 16))
                    except Exception:
                        return m.group(0)

                res = re.sub(r"\\x([0-9a-fA-F]{2})", _hex_repl, text)
                res = re.sub(r"\\u([0-9a-fA-F]{4})", _uni_repl, res)
                return res

            def _check_string_for_restricted_code(val: str, path: str):
                decoded_val = _decode_escapes(val)
                for pattern, desc in RESTRICTED_CODE_PATTERNS:
                    if re.search(pattern, val, re.IGNORECASE) or re.search(pattern, decoded_val, re.IGNORECASE):
                        report.add_issue(
                            ValidationIssue(
                                severity=ValidationIssueSeverity.FATAL,
                                rule_code="RESTRICTED_CODE_SANDBOX",
                                node_id=node.id,
                                property_path=path,
                                message=(
                                    f"Code node '{node.name}' contains disallowed code pattern: {desc}. "
                                    "Host process execution and direct filesystem calls are prohibited in workflow code."
                                ),
                                suggested_fix="Remove process/filesystem access calls and use standard workflow transformations or HTTP Request nodes."
                            )
                        )
                        break

            def _traverse_params(obj: Any, path: str):
                if isinstance(obj, str):
                    _check_string_for_restricted_code(obj, path)
                elif isinstance(obj, dict):
                    for k, v in obj.items():
                        _traverse_params(v, f"{path}.{k}" if path else k)
                elif isinstance(obj, list):
                    for idx, item in enumerate(obj):
                        _traverse_params(item, f"{path}[{idx}]")

            _traverse_params(node.parameters, "parameters")

        # A. Check Node Type Availability
        if not self.registry.is_node_supported(node.node_type):
            report.add_issue(
                ValidationIssue(
                    severity=ValidationIssueSeverity.FATAL,
                    rule_code="NODE_TYPE_UNKNOWN",
                    node_id=node.id,
                    message=(
                        f"Node type '{node.node_type}' on node '{node.name}' is not recognized or installed "
                        f"in the target n8n instance ({self.registry.provenance.get('n8n_version', 'current')})."
                    ),
                    suggested_fix="Replace with a supported n8n node type or check spelling."
                )
            )
            # Record that deeper schema checks could not be completed
            report.checks_skipped = True
            return

        node_def: Optional[NodeDefinition] = self.registry.get_node(node.node_type)
        if not node_def:
            report.checks_skipped = True
            return

        # B. Check Version Compatibility
        if not self.registry.is_version_supported(node.node_type, node.type_version):
            report.add_issue(
                ValidationIssue(
                    severity=ValidationIssueSeverity.WARNING,
                    rule_code="NODE_VERSION_UNSUPPORTED",
                    node_id=node.id,
                    message=(
                        f"Node '{node.name}' uses typeVersion {node.type_version}, which is not in the installed "
                        f"supported versions {node_def.supported_versions}. Default is {node_def.default_version}."
                    ),
                    suggested_fix=f"Use default typeVersion {node_def.default_version} for maximum compatibility."
                )
            )

        # C. Check Operation Compatibility
        if node.operation:
            supported_ops = node_def.get_operations(version=node.type_version)
            if supported_ops and not self.registry.is_operation_supported(
                node.node_type, node.operation, version=node.type_version
            ):
                report.add_issue(
                    ValidationIssue(
                        severity=ValidationIssueSeverity.FATAL,
                        rule_code="NODE_OPERATION_UNSUPPORTED",
                        node_id=node.id,
                        property_path="operation",
                        message=(
                            f"Operation '{node.operation}' is not supported by node '{node.name}'. "
                            f"Supported operations: {supported_ops[:10]}."
                        ),
                        suggested_fix=f"Select one of the supported operations: {', '.join(supported_ops[:5])}."
                    )
                )

        # D. Dynamic or Incomplete Schema Tracking
        if node_def.inputs == "dynamic" or node_def.outputs == "dynamic":
            report.add_issue(
                ValidationIssue(
                    severity=ValidationIssueSeverity.INFO,
                    rule_code="SCHEMA_INCOMPLETE_CHECK_SKIPPED",
                    node_id=node.id,
                    message=(
                        f"Node '{node.name}' ({node.node_type}) declares dynamic input/output sockets. "
                        "Static socket bound checking was skipped for this node."
                    ),
                    suggested_fix=None
                )
            )
            report.checks_skipped = True

        # E. Validate Statically Known Socket Bounds from Registry
        if isinstance(node_def.outputs, list):
            max_outputs = len(node_def.outputs)
            outgoing = workflow.get_outgoing_edges(node.id)
            for edge in outgoing:
                if edge.source_output_index >= max_outputs:
                    # Only add if not already captured by baseline rule
                    if not any(
                        issue.rule_code == "INVALID_OUTPUT_INDEX" and issue.node_id == node.id
                        for issue in report.issues
                    ):
                        report.add_issue(
                            ValidationIssue(
                                severity=ValidationIssueSeverity.FATAL,
                                rule_code="INVALID_OUTPUT_INDEX",
                                node_id=node.id,
                                edge_source_id=edge.source_id,
                                edge_target_id=edge.target_id,
                                message=(
                                    f"Node '{node.name}' ({node.node_type}) specifies {max_outputs} outputs, "
                                    f"but edge references source_output_index={edge.source_output_index}."
                                ),
                                suggested_fix=f"Use output index between 0 and {max_outputs - 1}."
                            )
                        )

        # F. Parameter Validation
        props = node_def.get_properties(version=node.type_version)
        prop_map = {p.name: p for p in props}

        # 1. Check required parameters (both unconditional and conditionally active for current operation)
        for prop in props:
            if prop.required:
                if is_property_visible(prop.display_options, node.parameters):
                    val = node.parameters.get(prop.name)
                    is_missing = False
                    if val is None:
                        is_missing = True
                    elif isinstance(val, str) and not val.strip():
                        is_missing = True
                    elif isinstance(val, dict):
                        # For resourceLocator (e.g. {"mode": "id", "value": ""}), check value field
                        if "value" in val and not str(val["value"]).strip():
                            is_missing = True
                    if is_missing:
                        report.add_issue(
                            ValidationIssue(
                                severity=ValidationIssueSeverity.FATAL,
                                rule_code="MISSING_REQUIRED_PARAMETER",
                                category="missing_required_config",
                                node_id=node.id,
                                property_path=f"parameters.{prop.name}",
                                message=f"Missing required parameter '{prop.name}' ({prop.display_name}) on node '{node.name}'.",
                                suggested_fix=f"Provide a valid value for parameter '{prop.name}'."
                            )
                        )

        # 2. Check parameter types and enum options
        for param_name, param_val in node.parameters.items():
            candidate_props = [p for p in props if p.name == param_name]
            if not candidate_props:
                continue
            active_matching = [p for p in candidate_props if is_property_visible(p.display_options, node.parameters)]
            prop = active_matching[0] if active_matching else candidate_props[0]

            # If expression string '{{ ... }}', skip static type constraints
            is_expression = isinstance(param_val, str) and ("{{" in param_val and "}}" in param_val)
            if is_expression:
                continue

            # Check option / enum values
            if prop.type == "options" and prop.options:
                allowed = prop.allowed_values
                if allowed and param_val not in allowed:
                    report.add_issue(
                        ValidationIssue(
                            severity=ValidationIssueSeverity.FATAL,
                            rule_code="INVALID_PARAMETER_OPTION",
                            category="invalid_parameter",
                            node_id=node.id,
                            property_path=f"parameters.{param_name}",
                            message=(
                                f"Value '{param_val}' for parameter '{param_name}' on node '{node.name}' "
                                f"is not a valid option. Allowed options: {allowed}."
                            ),
                            suggested_fix=f"Set '{param_name}' to one of {allowed}."
                        )
                    )

            # Check basic primitive types
            elif prop.type == "number" and not isinstance(param_val, (int, float)):
                if not (isinstance(param_val, str) and param_val.replace(".", "", 1).isdigit()):
                    report.add_issue(
                        ValidationIssue(
                            severity=ValidationIssueSeverity.FATAL,
                            rule_code="INVALID_PARAMETER_TYPE",
                            category="invalid_parameter",
                            node_id=node.id,
                            property_path=f"parameters.{param_name}",
                            message=(
                                f"Parameter '{param_name}' on node '{node.name}' expected a number, "
                                f"got {type(param_val).__name__} ('{param_val}')."
                            ),
                            suggested_fix=f"Provide a numeric value for '{param_name}'."
                        )
                    )
            elif prop.type == "boolean" and not isinstance(param_val, bool):
                report.add_issue(
                    ValidationIssue(
                        severity=ValidationIssueSeverity.FATAL,
                        rule_code="INVALID_PARAMETER_TYPE",
                        category="invalid_parameter",
                        node_id=node.id,
                        property_path=f"parameters.{param_name}",
                        message=(
                            f"Parameter '{param_name}' on node '{node.name}' expected boolean True/False, "
                            f"got {type(param_val).__name__}."
                        ),
                        suggested_fix=f"Set '{param_name}' to true or false."
                    )
                )

        # G. Credential Checks
        # 1. Required credentials check (operation-aware & alternative-mode aware)
        expected_creds = node_def.get_expected_credentials(node.parameters, node.credentials)
        for cred in expected_creds:
            if cred.required:
                if not node.credentials or cred.name not in node.credentials:
                    report.add_issue(
                        ValidationIssue(
                            severity=ValidationIssueSeverity.WARNING,
                            rule_code="MISSING_REQUIRED_CREDENTIAL",
                            category="missing_required_config",
                            node_id=node.id,
                            property_path=f"credentials.{cred.name}",
                            message=(
                                f"Node '{node.name}' ({node.node_type}) requires a credential reference "
                                f"for '{cred.name}', but none was supplied."
                            ),
                            suggested_fix=f"Configure a credential reference for '{cred.name}' in n8n (Credentials → New → {cred.name})."
                        )
                    )

        # 2. Check for literal secrets exposed in credential mappings
        if node.credentials:
            raw_secret_keys = {"password", "secret", "apikey", "api_key", "token", "private_key", "auth_token"}
            for cred_name, cred_val in node.credentials.items():
                if isinstance(cred_val, dict):
                    has_secrets = any(k.lower() in raw_secret_keys for k in cred_val.keys())
                    if has_secrets:
                        report.add_issue(
                            ValidationIssue(
                                severity=ValidationIssueSeverity.WARNING,
                                rule_code="INSECURE_CREDENTIAL_DATA",
                                node_id=node.id,
                                property_path=f"credentials.{cred_name}",
                                message=(
                                    f"Credential mapping '{cred_name}' on node '{node.name}' appears to embed "
                                    "literal secret values rather than an indirect credential ID or reference."
                                ),
                                suggested_fix="Replace literal secrets with a logical credential reference (e.g. {'id': '...'} or {'name': '...'})."
                            )
                        )
        # H. Expression syntax & parameter secret checks
        for p_key, p_val in node.parameters.items():
            if isinstance(p_val, str) and "{{" in p_val:
                open_count = p_val.count("{{")
                close_count = p_val.count("}}")
                if open_count != close_count:
                    report.add_issue(
                        ValidationIssue(
                            severity=ValidationIssueSeverity.FATAL,
                            rule_code="EXPRESSION_SYNTAX_ERROR",
                            node_id=node.id,
                            property_path=f"parameters.{p_key}",
                            message=(
                                f"Expression in parameter '{p_key}' on node '{node.name}' has unmatched braces: "
                                f"{open_count} '{{{{' vs {close_count} '}}}}'."
                            ),
                            suggested_fix="Ensure all expression tags '{{' are closed with matching '}}'.",
                        )
                    )

    def _validate_semantic_consistency(
        self,
        workflow: WorkflowIR,
        prompt_context: Optional[str],
        intent: Optional[Any],
        report: ValidationReport,
    ) -> None:
        """Compares requested intent and parameters against the generated graph."""
        # 1. Fabricated placeholder detection across all nodes
        BOGUS_CHAT_IDS = {"emcheckmebot", "bot", "mybot", "somebot", "chatid", "your_bot", "checkmebot"}
        BOGUS_TEXTS = {"gmail", "email", "placeholder", "test text"}

        for node in workflow.nodes:
            # Check Telegram / messaging parameters
            chat_id = node.parameters.get("chatId")
            if isinstance(chat_id, str) and chat_id.strip().lower() in BOGUS_CHAT_IDS:
                report.add_issue(
                    ValidationIssue(
                        severity=ValidationIssueSeverity.FATAL,
                        rule_code="FABRICATED_PLACEHOLDER_PARAMETER",
                        node_id=node.id,
                        property_path="parameters.chatId",
                        message=(
                            f"Node '{node.name}' uses inappropriate fabricated bot placeholder '{chat_id}'. "
                            "Use a valid chat destination or explicit configurable placeholder '<YOUR_TELEGRAM_CHAT_ID>'."
                        ),
                        suggested_fix="Set chatId to a real numeric chat ID, @channel, or '<YOUR_TELEGRAM_CHAT_ID>'."
                    )
                )

            text_val = node.parameters.get("text")
            if isinstance(text_val, str) and text_val.strip().lower() in BOGUS_TEXTS:
                report.add_issue(
                    ValidationIssue(
                        severity=ValidationIssueSeverity.FATAL,
                        rule_code="FABRICATED_PLACEHOLDER_PARAMETER",
                        node_id=node.id,
                        property_path="parameters.text",
                        message=(
                            f"Node '{node.name}' uses inappropriate placeholder '{text_val}'. "
                            "The notification message must map relevant workflow data expressions."
                        ),
                        suggested_fix="Map upstream fields using expressions, e.g. ={{ 'New email: ' + $json.subject }}."
                    )
                )

        # 2. Check condition node branch coverage and fault tolerance
        for node in workflow.nodes:
            if node.node_type in ("n8n-nodes-base.if", "if"):
                outgoing = workflow.get_outgoing_edges(node.id)
                output_indices = {edge.source_output_index for edge in outgoing}
                if 0 in output_indices and 1 not in output_indices:
                    report.add_issue(
                        ValidationIssue(
                            severity=ValidationIssueSeverity.INFO,
                            rule_code="BRANCH_COVERAGE_PARTIAL",
                            node_id=node.id,
                            message=(
                                f"Condition node '{node.name}' has an active True output branch (index 0) "
                                "but no connection from False output (index 1). "
                                "Items failing condition will be safely filtered out."
                            ),
                            suggested_fix="Connect output index 1 if secondary or fallback action handling is desired.",
                        )
                    )

            # Check fault tolerance policy
            exec_policy = getattr(node, "execution_policy", None)
            if exec_policy and (exec_policy.continue_on_fail or exec_policy.retry_on_fail):
                report.add_issue(
                    ValidationIssue(
                        severity=ValidationIssueSeverity.INFO,
                        rule_code="FAULT_TOLERANCE_CONFIGURED",
                        node_id=node.id,
                        message=f"Node '{node.name}' has fault tolerance policy configured.",
                    )
                )

        # 3. Check prompt or intent context if provided
        p_text = (prompt_context or "").lower()
        if intent:
            if hasattr(intent, "summary") and intent.summary:
                p_text += " " + intent.summary.lower()

        if not p_text.strip():
            return

        is_email_requested = any(
            phrase in p_text
            for phrase in [
                "receive an email", "when i receive an email", "when an email",
                "incoming email", "new email", "get an email", "email trigger",
                "emails arrive", "email arrives", "when i get email"
            ]
        ) or (intent and hasattr(intent, "trigger") and intent.trigger and getattr(intent.trigger, "service_name", "").lower() in ("email", "gmail", "imap", "outlook"))

        is_sheets_requested = any(
            phrase in p_text
            for phrase in [
                "google sheets", "google sheet", "spreadsheet", "new row", "row added"
            ]
        ) or (intent and hasattr(intent, "trigger") and intent.trigger and "sheet" in getattr(intent.trigger, "service_name", "").lower())

        is_telegram_requested = any(
            phrase in p_text
            for phrase in ["telegram", "telegram bot", "telegram message", "notification on telegram", "notify on telegram"]
        ) or (intent and hasattr(intent, "actions") and any(getattr(a, "service_name", "").lower() == "telegram" or getattr(a, "service", "").lower() == "telegram" for a in intent.actions))

        # Check Trigger Intent
        if is_email_requested:
            has_email_trigger = any(
                n.node_type in (
                    "n8n-nodes-base.gmailTrigger",
                    "n8n-nodes-base.emailReadImap",
                    "n8n-nodes-base.microsoftOutlookTrigger",
                    "gmailTrigger",
                    "emailReadImap",
                    "microsoftOutlookTrigger",
                )
                for n in workflow.nodes
            )
            has_manual_trigger = any(
                n.node_type in ("n8n-nodes-base.manualTrigger", "manualTrigger")
                for n in workflow.nodes
            )
            if not has_email_trigger and has_manual_trigger:
                report.add_issue(
                    ValidationIssue(
                        severity=ValidationIssueSeverity.FATAL,
                        rule_code="TRIGGER_INTENT_MISMATCH",
                        node_id=next((n.id for n in workflow.nodes if "manualtrigger" in n.node_type.lower()), None),
                        message=(
                            "Workflow uses 'Manual Trigger', but user requested an automated email trigger. "
                            "A real email trigger (n8n-nodes-base.gmailTrigger, n8n-nodes-base.microsoftOutlookTrigger, or n8n-nodes-base.emailReadImap) is required."
                        ),
                        suggested_fix="Replace 'Manual Trigger' with 'Gmail Trigger', 'Outlook Trigger', or 'Email Trigger (IMAP)'."
                    )
                )
            elif not has_email_trigger:
                report.add_issue(
                    ValidationIssue(
                        severity=ValidationIssueSeverity.FATAL,
                        rule_code="TRIGGER_INTENT_MISMATCH",
                        message=(
                            "User requested an automated email workflow, but no email trigger node was found in the graph."
                        ),
                        suggested_fix="Add 'n8n-nodes-base.gmailTrigger' or 'n8n-nodes-base.emailReadImap' as the workflow entrypoint."
                    )
                )

        # Dynamic trigger validation against intent.trigger if available
        if intent and hasattr(intent, "trigger") and intent.trigger and intent.trigger.is_supported and intent.trigger.node_type:
            expected_type = intent.trigger.node_type
            if expected_type != "n8n-nodes-base.manualTrigger":
                has_expected = any(n.node_type == expected_type for n in workflow.nodes)
                has_manual = any(n.node_type in ("n8n-nodes-base.manualTrigger", "manualTrigger") for n in workflow.nodes)
                if has_manual and not has_expected:
                    if not any(iss.rule_code == "TRIGGER_INTENT_MISMATCH" for iss in report.issues):
                        report.add_issue(
                            ValidationIssue(
                                severity=ValidationIssueSeverity.FATAL,
                                rule_code="TRIGGER_INTENT_MISMATCH",
                                node_id=next((n.id for n in workflow.nodes if "manualtrigger" in n.node_type.lower()), None),
                                message=(
                                    f"Workflow uses 'Manual Trigger', but user requested an automated {intent.trigger.service_name} trigger. "
                                    f"'{expected_type}' is required."
                                ),
                                suggested_fix=f"Replace 'Manual Trigger' with '{expected_type}'."
                            )
                        )

        if is_sheets_requested and not is_email_requested:
            has_sheets_trigger = any(
                "googlesheetstrigger" in n.node_type.lower()
                for n in workflow.nodes
            )
            has_manual_trigger = any(
                n.node_type in ("n8n-nodes-base.manualTrigger", "manualTrigger")
                for n in workflow.nodes
            )
            if not has_sheets_trigger and has_manual_trigger:
                report.add_issue(
                    ValidationIssue(
                        severity=ValidationIssueSeverity.FATAL,
                        rule_code="TRIGGER_INTENT_MISMATCH",
                        node_id=next((n.id for n in workflow.nodes if "manualtrigger" in n.node_type.lower()), None),
                        message=(
                            "Workflow uses 'Manual Trigger', but user requested an automated Google Sheets trigger. "
                            "'n8n-nodes-base.googleSheetsTrigger' is required."
                        ),
                        suggested_fix="Replace 'Manual Trigger' with 'n8n-nodes-base.googleSheetsTrigger'."
                    )
                )
            elif not has_sheets_trigger:
                report.add_issue(
                    ValidationIssue(
                        severity=ValidationIssueSeverity.FATAL,
                        rule_code="TRIGGER_INTENT_MISMATCH",
                        message=(
                            "User requested an automated Google Sheets workflow, but no Google Sheets trigger node was found in the graph."
                        ),
                        suggested_fix="Add 'n8n-nodes-base.googleSheetsTrigger' as the workflow entrypoint."
                    )
                )

        # Check Action Intent
        if is_telegram_requested:
            tg_nodes = [
                n for n in workflow.nodes
                if "telegram" in n.node_type.lower() and not _is_trigger_node(n.node_type)
            ]
            if not tg_nodes:
                report.add_issue(
                    ValidationIssue(
                        severity=ValidationIssueSeverity.FATAL,
                        rule_code="ACTION_INTENT_MISMATCH",
                        message=(
                            "User requested a Telegram notification, but no Telegram action node was generated."
                        ),
                        suggested_fix="Add an 'n8n-nodes-base.telegram' node configured to send a message."
                    )
                )
            else:
                for tg in tg_nodes:
                    tg_op = tg.operation or tg.parameters.get("operation")
                    if tg_op and tg_op not in ("sendMessage", "sendRichMessage", "sendPhoto", "sendDocument"):
                        report.add_issue(
                            ValidationIssue(
                                severity=ValidationIssueSeverity.FATAL,
                                rule_code="INVALID_NOTIFICATION_OPERATION",
                                node_id=tg.id,
                                property_path="parameters.operation",
                                message=(
                                    f"Telegram node '{tg.name}' uses operation '{tg_op}', but delivering a notification requires 'sendMessage'."
                                ),
                                suggested_fix="Set operation to 'sendMessage' and resource to 'message'."
                            )
                        )

                    # Upstream expression mapping check
                    msg_text = str(tg.parameters.get("text", ""))
                    if not ("$json" in msg_text or "{{" in msg_text):
                        report.add_issue(
                            ValidationIssue(
                                severity=ValidationIssueSeverity.WARNING,
                                rule_code="DATA_FLOW_UNMAPPED",
                                category="unresolved_data_mapping",
                                node_id=tg.id,
                                property_path="parameters.text",
                                message=(
                                    f"Telegram node '{tg.name}' message does not reference upstream event data ($json). "
                                    "Notification will not show incoming event data."
                                ),
                                suggested_fix="Map upstream fields: e.g. ={{ 'Event: ' + JSON.stringify($json) }}"
                            )
                        )
                    elif intent and hasattr(intent, "data_mappings") and intent.data_mappings:
                        missing_mappings = []
                        for m in intent.data_mappings:
                            from_field = m.get("from", "")
                            if from_field.startswith("sheets."):
                                col_name = from_field[len("sheets."):].lower()
                                if col_name not in msg_text.lower():
                                    missing_mappings.append(col_name)
                        if missing_mappings:
                            report.add_issue(
                                ValidationIssue(
                                    severity=ValidationIssueSeverity.WARNING,
                                    rule_code="UNRESOLVED_DATA_MAPPING",
                                    category="unresolved_data_mapping",
                                    node_id=tg.id,
                                    property_path="parameters.text",
                                    message=(
                                        f"Telegram message on node '{tg.name}' does not map requested column(s): {', '.join(missing_mappings)}. "
                                        "Ensure all requested data columns are mapped into the notification."
                                    ),
                                    suggested_fix=f"Include {', '.join(['$json.' + c for c in missing_mappings])} in parameters.text expression."
                                )
                            )


def validate_workflow(
    workflow: WorkflowIR,
    registry: Optional[NodeRegistry] = None,
    prompt_context: Optional[str] = None,
    intent: Optional[Any] = None,
) -> ValidationReport:
    """Convenience functional validation entrypoint."""
    validator = WorkflowValidator(registry=registry)
    return validator.validate(workflow, prompt_context=prompt_context, intent=intent)
