"""Unit tests for n8n credential resolution, validation, readiness consistency, and compilation."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.schemas.ir import IREdge, IRNode, WorkflowIR
from backend.app.schemas.readiness import (
    CredentialVerificationState,
    ReadinessItemStatus,
    ReadinessStatus,
)
from backend.app.services.compiler import WorkflowCompiler
from backend.app.services.n8n_client import N8nClient
from backend.app.services.node_registry import NodeRegistry
from backend.app.services.readiness import WorkflowReadinessEvaluator
from backend.app.services.validator import WorkflowValidator


@pytest.fixture
def registry():
    return NodeRegistry()


@pytest.fixture
def validator(registry):
    return WorkflowValidator(registry=registry)


@pytest.fixture
def readiness_evaluator(registry):
    return WorkflowReadinessEvaluator(registry=registry)


@pytest.fixture
def compiler(registry):
    return WorkflowCompiler(registry=registry)


# ---------------------------------------------------------------------------
# 1. Inspect installed node definitions: get_expected_credentials
# ---------------------------------------------------------------------------


def test_google_sheets_trigger_expected_credentials(registry):
    """Google Sheets Trigger requires googleSheetsTriggerOAuth2Api by default,

    or googleApi only if serviceAccount is explicitly selected.
    It must NEVER require both simultaneously.
    """
    node_def = registry.get_node("n8n-nodes-base.googleSheetsTrigger")
    assert node_def is not None

    # Default / triggerOAuth2 mode
    expected_default = node_def.get_expected_credentials()
    assert len(expected_default) == 1
    assert expected_default[0].name == "googleSheetsTriggerOAuth2Api"
    assert expected_default[0].required is True

    # Explicit serviceAccount mode
    expected_sa = node_def.get_expected_credentials(parameters={"authentication": "serviceAccount"})
    assert len(expected_sa) == 1
    assert expected_sa[0].name == "googleApi"
    assert expected_sa[0].required is True


def test_google_sheets_action_expected_credentials(registry):
    """Google Sheets action requires googleSheetsOAuth2Api by default,

    or googleApi only if serviceAccount is selected.
    """
    node_def = registry.get_node("n8n-nodes-base.googleSheets")
    assert node_def is not None

    expected_default = node_def.get_expected_credentials()
    assert len(expected_default) == 1
    assert expected_default[0].name == "googleSheetsOAuth2Api"

    expected_sa = node_def.get_expected_credentials(parameters={"authentication": "serviceAccount"})
    assert len(expected_sa) == 1
    assert expected_sa[0].name == "googleApi"


def test_telegram_expected_credentials(registry):
    """Telegram node requires telegramApi."""
    node_def = registry.get_node("n8n-nodes-base.telegram")
    assert node_def is not None

    expected = node_def.get_expected_credentials()
    assert len(expected) == 1
    assert expected[0].name == "telegramApi"
    assert expected[0].required is True


def test_slack_expected_credentials(registry):
    """Slack node requires slackApi for accessToken and slackOAuth2Api for oAuth2."""
    node_def = registry.get_node("n8n-nodes-base.slack")
    assert node_def is not None

    expected_token = node_def.get_expected_credentials(parameters={"authentication": "accessToken"})
    assert len(expected_token) == 1
    assert expected_token[0].name == "slackApi"

    expected_oauth = node_def.get_expected_credentials(parameters={"authentication": "oAuth2"})
    assert len(expected_oauth) == 1
    assert expected_oauth[0].name == "slackOAuth2Api"


# ---------------------------------------------------------------------------
# 2. Validator credential checking uses operation-specific expected credentials
# ---------------------------------------------------------------------------


def test_validator_google_sheets_trigger_no_spurious_google_api(validator):
    """Workflow with Google Sheets Trigger using OAuth2 must NOT report

    missing googleApi credential.
    """
    workflow = WorkflowIR(
        id="wf_gst_valid",
        name="Google Sheets Trigger Valid",
        nodes=[
            IRNode(
                id="trigger_1",
                name="Google Sheets Trigger",
                node_type="n8n-nodes-base.googleSheetsTrigger",
                type_version=1,
                parameters={
                    "pollTimes": {"item": [{"mode": "everyMinute"}]},
                    "documentId": "sheet_123",
                    "sheetName": "Sheet1",
                    "event": "rowAdded",
                },
                credentials={"googleSheetsTriggerOAuth2Api": {"id": "cred_gst_1"}},
            ),
            IRNode(
                id="telegram_1",
                name="Telegram",
                node_type="n8n-nodes-base.telegram",
                type_version=1,
                parameters={
                    "resource": "message",
                    "operation": "sendMessage",
                    "chatId": "12345678",
                    "text": "New row: {{$json.Name}}",
                },
                credentials={"telegramApi": {"id": "cred_tg_1"}},
            ),
        ],
        edges=[IREdge(source_id="trigger_1", target_id="telegram_1")],
    )

    report = validator.validate(workflow)
    # No missing credential issues should exist
    cred_issues = [i for i in report.issues if i.rule_code == "MISSING_REQUIRED_CREDENTIAL"]
    assert len(cred_issues) == 0


def test_validator_flags_missing_credential_when_omitted(validator):
    """Workflow with Google Sheets Trigger omitting credentials must flag

    missing googleSheetsTriggerOAuth2Api (and NOT googleApi).
    """
    workflow = WorkflowIR(
        id="wf_gst_missing",
        name="Google Sheets Trigger Missing",
        nodes=[
            IRNode(
                id="trigger_1",
                name="Google Sheets Trigger",
                node_type="n8n-nodes-base.googleSheetsTrigger",
                type_version=1,
                parameters={"documentId": "sheet_123", "sheetName": "Sheet1"},
                credentials={},
            )
        ],
        edges=[],
    )

    report = validator.validate(workflow)
    cred_issues = [i for i in report.issues if i.rule_code == "MISSING_REQUIRED_CREDENTIAL"]
    assert len(cred_issues) == 1
    assert "googleSheetsTriggerOAuth2Api" in cred_issues[0].message
    assert "googleApi" not in cred_issues[0].message


# ---------------------------------------------------------------------------
# 3. Readiness Service: Credential States (missing, referenced, configured, invalid)
# ---------------------------------------------------------------------------


def test_readiness_five_credential_states(readiness_evaluator):
    """Tests that the readiness evaluator correctly differentiates:

    1. missing
    2. referenced
    3. configured (matched in n8n)
    4. invalid (id specified not found in n8n)
    5. insecure_literal
    """
    available_n8n = [
        {"id": "n8n_tg_999", "name": "My Telegram Bot", "type": "telegramApi"},
        {"id": "n8n_gst_111", "name": "Google Sheets Work", "type": "googleSheetsTriggerOAuth2Api"},
    ]

    # Node with configured (matched) credential
    wf_configured = WorkflowIR(
        id="wf_conf",
        name="Configured Workflow",
        nodes=[
            IRNode(
                id="tg_1",
                name="Telegram",
                node_type="n8n-nodes-base.telegram",
                type_version=1,
                parameters={"chatId": "123456", "text": "hello"},
                credentials={"telegramApi": {"id": "n8n_tg_999"}},
            )
        ],
        edges=[],
    )
    rep_conf = readiness_evaluator.evaluate(wf_configured, available_n8n_credentials=available_n8n)
    tg_item = next(c for c in rep_conf.credentials if c.credential_type == "telegramApi")
    assert tg_item.verification_state == CredentialVerificationState.CONFIGURED
    assert "n8n_tg_999" in str(tg_item.configured_reference)

    # Node with invalid credential ID (ID not in n8n)
    wf_invalid = WorkflowIR(
        id="wf_inv",
        name="Invalid Workflow",
        nodes=[
            IRNode(
                id="tg_1",
                name="Telegram",
                node_type="n8n-nodes-base.telegram",
                type_version=1,
                parameters={"chatId": "123456", "text": "hello"},
                credentials={"telegramApi": {"id": "non_existent_id"}},
            )
        ],
        edges=[],
    )
    rep_inv = readiness_evaluator.evaluate(wf_invalid, available_n8n_credentials=available_n8n)
    tg_inv = next(c for c in rep_inv.credentials if c.credential_type == "telegramApi")
    assert tg_inv.verification_state == CredentialVerificationState.INVALID
    assert rep_inv.is_deployment_ready is False

    # Node with missing credential
    wf_missing = WorkflowIR(
        id="wf_miss",
        name="Missing Workflow",
        nodes=[
            IRNode(
                id="tg_1",
                name="Telegram",
                node_type="n8n-nodes-base.telegram",
                type_version=1,
                parameters={"chatId": "123456", "text": "hello"},
                credentials={},
            )
        ],
        edges=[],
    )
    rep_miss = readiness_evaluator.evaluate(wf_missing, available_n8n_credentials=available_n8n)
    tg_miss = next(c for c in rep_miss.credentials if c.credential_type == "telegramApi")
    assert tg_miss.verification_state == CredentialVerificationState.MISSING
    assert rep_miss.is_deployment_ready is False

    # Node with insecure literal secret
    wf_literal = WorkflowIR(
        id="wf_lit",
        name="Literal Secret Workflow",
        nodes=[
            IRNode(
                id="tg_1",
                name="Telegram",
                node_type="n8n-nodes-base.telegram",
                type_version=1,
                parameters={"chatId": "123456", "text": "hello"},
                credentials={"telegramApi": {"token": "secret_token_123"}},
            )
        ],
        edges=[],
    )
    rep_lit = readiness_evaluator.evaluate(wf_literal, available_n8n_credentials=available_n8n)
    tg_lit = next(c for c in rep_lit.credentials if c.credential_type == "telegramApi")
    assert tg_lit.verification_state == CredentialVerificationState.INSECURE_LITERAL
    assert rep_lit.is_deployment_ready is False


# ---------------------------------------------------------------------------
# 4. Readiness Consistency: Deploy Ready MUST be False when credentials missing
# ---------------------------------------------------------------------------


def test_readiness_consistency_no_deploy_ready_when_missing_credentials(readiness_evaluator):
    """A workflow with complete parameters but missing credentials MUST have

    is_deployment_ready = False and overall_status = NEEDS_ATTENTION.
    It must NEVER report Deploy Ready: Ready when credentials are unresolved.
    """
    workflow = WorkflowIR(
        id="wf_gst_tg_unconfigured",
        name="Google Sheets to Telegram Unconfigured",
        nodes=[
            IRNode(
                id="trigger_1",
                name="Google Sheets Trigger",
                node_type="n8n-nodes-base.googleSheetsTrigger",
                type_version=1,
                parameters={
                    "pollTimes": {"item": [{"mode": "everyMinute"}]},
                    "documentId": "sheet_abc123",
                    "sheetName": "Sheet1",
                    "event": "rowAdded",
                },
                credentials={},  # Missing!
            ),
            IRNode(
                id="tg_1",
                name="Telegram",
                node_type="n8n-nodes-base.telegram",
                type_version=1,
                parameters={
                    "resource": "message",
                    "operation": "sendMessage",
                    "chatId": "987654321",
                    "text": "Name: {{$json.Name}}",
                },
                credentials={},  # Missing!
            ),
        ],
        edges=[IREdge(source_id="trigger_1", target_id="tg_1")],
    )

    report = readiness_evaluator.evaluate(workflow)

    # Contradiction check:
    assert report.is_structure_valid is True
    assert report.is_deployment_ready is False  # Must be False!
    assert report.overall_status == ReadinessStatus.NEEDS_ATTENTION
    assert "credentials are missing" in report.summary

    # Ensure exactly 2 credentials reported (not 3)
    assert len(report.credentials) == 2
    assert {c.credential_type for c in report.credentials} == {
        "googleSheetsTriggerOAuth2Api",
        "telegramApi",
    }


# ---------------------------------------------------------------------------
# 5. Compiler output credential format
# ---------------------------------------------------------------------------


def test_compiler_normalizes_credentials(compiler):
    """Compiler must normalize credentials into the standard n8n dict format

    {'credType': {'id': 'xyz'}} even if given as string ID or dict.
    """
    workflow = WorkflowIR(
        id="wf_compile_test",
        name="Compile Test",
        nodes=[
            IRNode(
                id="node_1",
                name="Google Sheets Trigger",
                node_type="n8n-nodes-base.googleSheetsTrigger",
                type_version=1,
                parameters={"documentId": "doc123", "sheetName": "Sheet1"},
                credentials={"googleSheetsTriggerOAuth2Api": "cred_id_str"},
            ),
            IRNode(
                id="node_2",
                name="Telegram",
                node_type="n8n-nodes-base.telegram",
                type_version=1,
                parameters={"chatId": "123", "text": "hi"},
                credentials={"telegramApi": {"id": "cred_id_dict", "name": "My Bot"}},
            ),
        ],
        edges=[IREdge(source_id="node_1", target_id="node_2")],
    )

    compiled = compiler.compile(workflow)
    nodes = {n["name"]: n for n in compiled["nodes"]}

    gst_creds = nodes["Google Sheets Trigger"].get("credentials")
    assert gst_creds == {"googleSheetsTriggerOAuth2Api": {"id": "cred_id_str"}}

    tg_creds = nodes["Telegram"].get("credentials")
    assert tg_creds == {"telegramApi": {"id": "cred_id_dict", "name": "My Bot"}}


# ---------------------------------------------------------------------------
# 6. N8nClient.get_credentials safe metadata retrieval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_n8n_client_get_credentials_safe_metadata():
    """N8nClient.get_credentials extracts safe metadata (id, name, type)

    and never exposes secrets.
    """
    client = N8nClient()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {
                "id": "1",
                "name": "My Google Sheets",
                "type": "googleSheetsTriggerOAuth2Api",
                "data": {"clientSecret": "SUPER_SECRET_TOKEN_DO_NOT_EXPOSE"},
                "createdAt": "2026-01-01T00:00:00.000Z",
                "updatedAt": "2026-01-02T00:00:00.000Z",
            },
            {
                "id": "2",
                "name": "Production Bot",
                "type": "telegramApi",
                "data": {"accessToken": "123456:SECRET_BOT_TOKEN"},
                "createdAt": "2026-01-01T00:00:00.000Z",
                "updatedAt": "2026-01-02T00:00:00.000Z",
            },
        ]
    }

    with patch.object(client._http_client, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_response
        creds = await client.get_credentials()

        assert len(creds) == 2
        for cred in creds:
            # Safe fields present
            assert "id" in cred
            assert "name" in cred
            assert "type" in cred
            # Secrets strictly absent
            assert "data" not in cred
            assert "clientSecret" not in cred
            assert "accessToken" not in cred
