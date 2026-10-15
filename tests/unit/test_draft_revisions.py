"""Unit tests for safe workflow draft revisions, validation, and optimistic concurrency."""
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

from backend.app.api.v1.conversations import (
    DeployWorkflowRequest,
    DeployWorkflowResponse,
    SaveDraftRevisionRequest,
    ValidateWorkflowRequest,
    deploy_draft_workflow,
    get_draft_revision,
    get_node_definition,
    list_draft_revisions,
    save_draft_revision,
    validate_draft,
)
from backend.app.models.conversation import Conversation
from backend.app.models.workflow import WorkflowDraft, WorkflowRevision
from backend.app.schemas.ir import ConnectionType, IREdge, IRNode, WorkflowIR
from backend.app.services.compiler import WorkflowCompiler
from backend.app.services.node_registry import NodeRegistry
from backend.app.services.readiness import WorkflowReadinessEvaluator
from backend.app.services.validator import WorkflowValidator
from backend.app.services.n8n_client import (
    N8nClient,
    N8nConnectionState,
    N8nDeploymentError,
    N8nDeploymentTimeoutError,
    N8nStatusResponse,
    N8nWorkflowCreationResult,
)


class MockRevisionSession:
    """Mock async database session for unit testing draft revision operations."""

    def __init__(self, conversation: Conversation, draft: WorkflowDraft, revisions: list):
        self.conversation = conversation
        self.draft = draft
        self.revisions = revisions
        self.added = []

    async def execute(self, stmt):
        mock_res = MagicMock()
        stmt_str = str(stmt).lower()

        if "from conversations" in stmt_str:
            mock_res.scalar_one_or_none.return_value = self.conversation
            mock_res.scalar.return_value = self.conversation.id if self.conversation else None
        elif "from workflow_drafts" in stmt_str:
            mock_res.scalar_one_or_none.return_value = self.draft
        elif "max(workflow_revisions.revision_number)" in stmt_str:
            max_rev = max([r.revision_number for r in self.revisions], default=0)
            mock_res.scalar.return_value = max_rev
        elif "from workflow_revisions" in stmt_str:
            sorted_revs = sorted(self.revisions, key=lambda r: r.revision_number, reverse=True)
            if "workflow_revisions.revision_number =" in stmt_str or "workflow_revisions.id =" in stmt_str:
                mock_res.scalar_one_or_none.return_value = self.revisions[0] if self.revisions else None
            else:
                mock_res.scalars.return_value.all.return_value = sorted_revs
                mock_res.scalars.return_value.first.return_value = sorted_revs[0] if sorted_revs else None
        return mock_res

    def add(self, entity):
        self.added.append(entity)
        if isinstance(entity, WorkflowRevision):
            self.revisions.append(entity)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def refresh(self, entity):
        pass


@pytest.fixture
def sample_valid_ir() -> dict:
    return {
        "id": "wf_test_001",
        "name": "Test Automation",
        "nodes": [
            {
                "id": "n1",
                "name": "Schedule Trigger",
                "node_type": "n8n-nodes-base.scheduleTrigger",
                "type_version": 1.2,
                "parameters": {},
            },
            {
                "id": "n2",
                "name": "HTTP Call",
                "node_type": "n8n-nodes-base.httpRequest",
                "type_version": 4.2,
                "parameters": {"url": "https://example.com/api", "method": "GET"},
            },
        ],
        "edges": [
            {
                "source_id": "n1",
                "target_id": "n2",
                "connection_type": "main",
                "source_output_index": 0,
                "target_input_index": 0,
            }
        ],
    }


@pytest.fixture
def sample_invalid_ir() -> dict:
    return {
        "id": "wf_test_invalid",
        "name": "Missing Required Param",
        "nodes": [
            {
                "id": "n1",
                "name": "Schedule Trigger",
                "node_type": "n8n-nodes-base.scheduleTrigger",
                "type_version": 1.2,
            },
            {
                "id": "n2",
                "name": "HTTP Call",
                "node_type": "n8n-nodes-base.httpRequest",
                "type_version": 4.2,
                "parameters": {},  # Missing required 'url'
            },
        ],
        "edges": [
            {
                "source_id": "n1",
                "target_id": "n2",
            }
        ],
    }


@pytest.mark.asyncio
async def test_validate_draft_returns_report_without_persisting(sample_valid_ir):
    """Validate draft endpoint returns validation report and compiled JSON without touching database."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(id=conv_id, title="Test Flow")
    session = MockRevisionSession(conversation=conv, draft=None, revisions=[])

    validator = WorkflowValidator(registry=NodeRegistry())
    compiler = WorkflowCompiler()

    req = ValidateWorkflowRequest(workflow_ir=sample_valid_ir)
    res = await validate_draft(
        conversation_id=conv_id,
        payload=req,
        db=session,
        validator=validator,
        compiler=compiler,
    )

    assert res.is_valid is True
    assert res.validation_report["is_valid"] is True
    assert res.compiled_json is not None
    assert "nodes" in res.compiled_json
    # Ensure no rows were added to session
    assert len(session.added) == 0


@pytest.mark.asyncio
async def test_save_draft_revision_sequential_number(sample_valid_ir):
    """Saving a draft revision persists sequential revision numbers and compiles n8n JSON."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(id=conv_id, title="Test Flow", metadata_json={"state": "validating"})
    draft = WorkflowDraft(id=str(uuid.uuid4()), conversation_id=conv_id, title="Test Flow", status="draft")

    session = MockRevisionSession(conversation=conv, draft=draft, revisions=[])
    validator = WorkflowValidator(registry=NodeRegistry())
    compiler = WorkflowCompiler()

    # Save Revision 1
    req1 = SaveDraftRevisionRequest(workflow_ir=sample_valid_ir, expected_revision_number=0)
    res1 = await save_draft_revision(
        conversation_id=conv_id,
        payload=req1,
        db=session,
        validator=validator,
        compiler=compiler,
    )

    assert res1.revision_number == 1
    assert res1.is_valid is True
    assert res1.status == "ready"
    assert res1.compiled_json is not None
    assert conv.metadata_json["state"] == "ready"

    # Save Revision 2
    req2 = SaveDraftRevisionRequest(workflow_ir=sample_valid_ir, expected_revision_number=1)
    res2 = await save_draft_revision(
        conversation_id=conv_id,
        payload=req2,
        db=session,
        validator=validator,
        compiler=compiler,
    )

    assert res2.revision_number == 2
    assert res2.is_valid is True


@pytest.mark.asyncio
async def test_stale_revision_conflict_409(sample_valid_ir):
    """Saving with an expected_revision_number behind current max triggers HTTP 409 Conflict."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(id=conv_id, title="Test Flow")
    draft = WorkflowDraft(id=str(uuid.uuid4()), conversation_id=conv_id, title="Test Flow")

    # Current revision is 2
    rev1 = WorkflowRevision(id=str(uuid.uuid4()), draft_id=draft.id, revision_number=1, workflow_ir={})
    rev2 = WorkflowRevision(id=str(uuid.uuid4()), draft_id=draft.id, revision_number=2, workflow_ir={})

    session = MockRevisionSession(conversation=conv, draft=draft, revisions=[rev1, rev2])
    validator = WorkflowValidator(registry=NodeRegistry())
    compiler = WorkflowCompiler()

    # Client tries to save expecting revision 1, but revision is already 2
    req = SaveDraftRevisionRequest(workflow_ir=sample_valid_ir, expected_revision_number=1)

    with pytest.raises(HTTPException) as exc_info:
        await save_draft_revision(
            conversation_id=conv_id,
            payload=req,
            db=session,
            validator=validator,
            compiler=compiler,
        )

    assert exc_info.value.status_code == 409
    assert "Stale revision conflict" in exc_info.value.detail


@pytest.mark.asyncio
async def test_validation_failure_prevents_ready_status(sample_invalid_ir):
    """An invalid draft must never be marked ready; status becomes 'invalid' with no compiled JSON."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(id=conv_id, title="Test Flow", metadata_json={"state": "ready"})
    draft = WorkflowDraft(id=str(uuid.uuid4()), conversation_id=conv_id, title="Test Flow", status="ready")

    session = MockRevisionSession(conversation=conv, draft=draft, revisions=[])
    validator = WorkflowValidator(registry=NodeRegistry())
    compiler = WorkflowCompiler()

    req = SaveDraftRevisionRequest(workflow_ir=sample_invalid_ir)
    res = await save_draft_revision(
        conversation_id=conv_id,
        payload=req,
        db=session,
        validator=validator,
        compiler=compiler,
    )

    assert res.is_valid is False
    assert res.status == "invalid"
    assert res.compiled_json is None
    # Invariant: Conversation state is never left 'ready'
    assert conv.metadata_json["state"] != "ready"


@pytest.mark.asyncio
async def test_list_and_get_draft_revisions():
    """List draft revisions returns summaries and get_draft_revision returns full IR."""
    conv_id = str(uuid.uuid4())
    draft = WorkflowDraft(id=str(uuid.uuid4()), conversation_id=conv_id, title="Test Flow")
    rev = WorkflowRevision(
        id="rev-uuid-123",
        draft_id=draft.id,
        revision_number=1,
        workflow_ir={"id": "wf", "name": "Test", "nodes": [{"id": "n1"}], "edges": []},
        compiled_json={"nodes": []},
        validation_report={"is_valid": True},
    )

    session = MockRevisionSession(conversation=None, draft=draft, revisions=[rev])

    summaries = await list_draft_revisions(conversation_id=conv_id, db=session)
    assert len(summaries) == 1
    assert summaries[0].revision_number == 1
    assert summaries[0].is_valid is True

    detail = await get_draft_revision(
        conversation_id=conv_id,
        revision_identifier="1",
        db=session,
    )
    assert detail.revision_number == 1
    assert detail.workflow_ir["id"] == "wf"


@pytest.mark.asyncio
async def test_node_definition_schema_lookup():
    """Introspection endpoint returns verified schema properties from the registry."""
    registry = NodeRegistry()
    node_def = await get_node_definition(node_type="n8n-nodes-base.httpRequest", node_registry=registry)

    assert node_def["name"] == "httpRequest"
    assert node_def["canonical_name"] == "n8n-nodes-base.httpRequest"
    assert len(node_def["properties"]) > 0

    with pytest.raises(HTTPException) as exc:
        await get_node_definition(node_type="n8n-nodes-base.fictionalNonExistentNode", node_registry=registry)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_sequential_save_and_stale_concurrency(sample_valid_ir):
    """Saving advances revision numbers, and subsequent saves must provide the latest confirmed revision."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(id=conv_id, title="Test Flow")
    draft = WorkflowDraft(id=str(uuid.uuid4()), conversation_id=conv_id, title="Test Flow")

    session = MockRevisionSession(conversation=conv, draft=draft, revisions=[])
    validator = WorkflowValidator(registry=NodeRegistry())
    compiler = WorkflowCompiler()

    # 1. Save Revision 1 (expected 0)
    req1 = SaveDraftRevisionRequest(workflow_ir=sample_valid_ir, expected_revision_number=0)
    res1 = await save_draft_revision(
        conversation_id=conv_id,
        payload=req1,
        db=session,
        validator=validator,
        compiler=compiler,
    )
    assert res1.revision_number == 1

    # 2. Save Revision 2 (expected 1)
    req2 = SaveDraftRevisionRequest(workflow_ir=sample_valid_ir, expected_revision_number=1)
    res2 = await save_draft_revision(
        conversation_id=conv_id,
        payload=req2,
        db=session,
        validator=validator,
        compiler=compiler,
    )
    assert res2.revision_number == 2

    # 3. Subsequent save using stale expected 1 MUST raise HTTP 409
    req_stale = SaveDraftRevisionRequest(workflow_ir=sample_valid_ir, expected_revision_number=1)
    with pytest.raises(HTTPException) as exc_info:
        await save_draft_revision(
            conversation_id=conv_id,
            payload=req_stale,
            db=session,
            validator=validator,
            compiler=compiler,
        )
    assert exc_info.value.status_code == 409
    assert "current revision is 2, expected 1" in exc_info.value.detail

    # 4. Subsequent save using confirmed revision 2 succeeds and advances to 3
    req3 = SaveDraftRevisionRequest(workflow_ir=sample_valid_ir, expected_revision_number=2)
    res3 = await save_draft_revision(
        conversation_id=conv_id,
        payload=req3,
        db=session,
        validator=validator,
        compiler=compiler,
    )
    assert res3.revision_number == 3


def test_readiness_evaluator_detects_google_sheets_and_telegram_placeholders():
    """Readiness evaluator marks placeholders as unconfigured and blocks deployment readiness."""
    registry = NodeRegistry()
    validator = WorkflowValidator(registry=registry)
    evaluator = WorkflowReadinessEvaluator(registry=registry, validator=validator)

    unconfigured_ir = WorkflowIR(
        id="wf_sheets_tg",
        name="Google Sheets to Telegram",
        nodes=[
            IRNode(
                id="n1",
                name="Google Sheets Trigger",
                node_type="n8n-nodes-base.googleSheetsTrigger",
                type_version=1.0,
                parameters={"event": "rowAdded", "documentId": "={{ '<YOUR_SPREADSHEET_ID>' }}", "sheetName": "Sheet1"},
            ),
            IRNode(
                id="n2",
                name="Telegram",
                node_type="n8n-nodes-base.telegram",
                type_version=1.2,
                parameters={"chatId": "={{ '<YOUR_TELEGRAM_CHAT_ID>' }}", "text": "New row added"},
            ),
        ],
        edges=[IREdge(source_id="n1", target_id="n2", connection_type=ConnectionType.MAIN)],
    )

    report = evaluator.evaluate(unconfigured_ir)
    assert report.is_structure_valid is True
    assert report.is_configuration_complete is False
    assert report.is_deployment_ready is False
    assert len(report.unresolved_configuration) >= 2
    assert any("Spreadsheet" in u or "documentId" in u for u in report.unresolved_configuration)
    assert any("Telegram" in u or "chatId" in u for u in report.unresolved_configuration)

    # Now provide real values
    configured_ir = WorkflowIR(
        id="wf_sheets_tg",
        name="Google Sheets to Telegram",
        nodes=[
            IRNode(
                id="n1",
                name="Google Sheets Trigger",
                node_type="n8n-nodes-base.googleSheetsTrigger",
                type_version=1.0,
                parameters={"event": "rowAdded", "documentId": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms", "sheetName": "Sheet1"},
                credentials={"googleSheetsTriggerOAuth2Api": {"id": "cred_sheets_1", "name": "Google Sheets"}},
            ),
            IRNode(
                id="n2",
                name="Telegram",
                node_type="n8n-nodes-base.telegram",
                type_version=1.2,
                parameters={"chatId": "123456789", "text": "New row added"},
                credentials={"telegramApi": {"id": "cred_tg_1", "name": "Telegram Bot"}},
            ),
        ],
        edges=[IREdge(source_id="n1", target_id="n2", connection_type=ConnectionType.MAIN)],
    )

    clean_report = evaluator.evaluate(configured_ir)
    assert clean_report.is_structure_valid is True
    assert clean_report.is_configuration_complete is True
    assert clean_report.is_deployment_ready is True
    assert len(clean_report.unresolved_configuration) == 0


@pytest.mark.asyncio
async def test_deploy_workflow_blocked_by_stale_revision(sample_valid_ir):
    """Deploying with a stale revision number is rejected with HTTP 409 Conflict."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(id=conv_id, title="Test Flow")
    draft = WorkflowDraft(id=str(uuid.uuid4()), conversation_id=conv_id, title="Test Flow")
    rev1 = WorkflowRevision(id=str(uuid.uuid4()), draft_id=draft.id, revision_number=1, workflow_ir=sample_valid_ir)
    rev2 = WorkflowRevision(id=str(uuid.uuid4()), draft_id=draft.id, revision_number=2, workflow_ir=sample_valid_ir)

    session = MockRevisionSession(conversation=conv, draft=draft, revisions=[rev1, rev2])
    registry = NodeRegistry()
    validator = WorkflowValidator(registry=registry)
    evaluator = WorkflowReadinessEvaluator(registry=registry, validator=validator)
    compiler = WorkflowCompiler()

    # User attempts to deploy expecting revision 1, but revision is 2
    req = DeployWorkflowRequest(expected_revision_number=1)

    with pytest.raises(HTTPException) as exc:
        await deploy_draft_workflow(
            conversation_id=conv_id,
            payload=req,
            db=session,
            evaluator=evaluator,
            compiler=compiler,
        )
    assert exc.value.status_code == 409
    assert "current saved revision is 2, expected 1" in exc.value.detail


@pytest.mark.asyncio
async def test_deploy_workflow_blocked_by_unconfigured_parameters():
    """Deploying a revision with unconfigured placeholders is rejected with HTTP 400 Bad Request."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(id=conv_id, title="Test Flow")
    draft = WorkflowDraft(id=str(uuid.uuid4()), conversation_id=conv_id, title="Test Flow")

    unconfigured_ir = {
        "id": "wf_unconf",
        "name": "Unconfigured Flow",
        "nodes": [
            {
                "id": "n1",
                "name": "Google Sheets Trigger",
                "node_type": "n8n-nodes-base.googleSheetsTrigger",
                "type_version": 1.0,
                "parameters": {"event": "rowAdded", "documentId": "={{ '<YOUR_SPREADSHEET_ID>' }}", "sheetName": "Sheet1"},
            },
            {
                "id": "n2",
                "name": "Telegram",
                "node_type": "n8n-nodes-base.telegram",
                "type_version": 1.2,
                "parameters": {"chatId": "={{ '<YOUR_TELEGRAM_CHAT_ID>' }}", "text": "Alert"},
            },
        ],
        "edges": [{"source_id": "n1", "target_id": "n2", "connection_type": "main"}],
    }

    rev = WorkflowRevision(id=str(uuid.uuid4()), draft_id=draft.id, revision_number=1, workflow_ir=unconfigured_ir)
    session = MockRevisionSession(conversation=conv, draft=draft, revisions=[rev])
    registry = NodeRegistry()
    validator = WorkflowValidator(registry=registry)
    evaluator = WorkflowReadinessEvaluator(registry=registry, validator=validator)
    compiler = WorkflowCompiler()

    req = DeployWorkflowRequest(expected_revision_number=1)

    with pytest.raises(HTTPException) as exc:
        await deploy_draft_workflow(
            conversation_id=conv_id,
            payload=req,
            db=session,
            evaluator=evaluator,
            compiler=compiler,
        )
    assert exc.value.status_code == 400
    assert "unconfigured required parameters" in exc.value.detail


@pytest.mark.asyncio
async def test_deploy_workflow_success_creates_inactive_workflow_in_n8n(sample_valid_ir):
    """Deploying a valid revision connects to n8n, creates workflow inactive, and returns workflow ID."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(id=conv_id, title="Test Flow", metadata_json={})
    draft = WorkflowDraft(id=str(uuid.uuid4()), conversation_id=conv_id, title="Test Flow", status="draft")
    rev = WorkflowRevision(id=str(uuid.uuid4()), draft_id=draft.id, revision_number=1, workflow_ir=sample_valid_ir)

    session = MockRevisionSession(conversation=conv, draft=draft, revisions=[rev])
    registry = NodeRegistry()
    validator = WorkflowValidator(registry=registry)
    evaluator = WorkflowReadinessEvaluator(registry=registry, validator=validator)
    compiler = WorkflowCompiler()

    mock_creation = N8nWorkflowCreationResult(
        workflow_id="n8n_wf_777",
        workflow_name="Test Automation",
        is_active=False,
        workflow_url="http://localhost:5678/workflow/n8n_wf_777",
    )

    with patch.object(N8nClient, "check_connection", new_callable=AsyncMock) as mock_check, \
         patch.object(N8nClient, "create_workflow", new_callable=AsyncMock) as mock_create:
        mock_check.return_value = N8nStatusResponse(status=N8nConnectionState.CONNECTED, message="Connected")
        mock_create.return_value = mock_creation

        req = DeployWorkflowRequest(expected_revision_number=1, idempotency_token="tok_123")
        res = await deploy_draft_workflow(
            conversation_id=conv_id,
            payload=req,
            db=session,
            evaluator=evaluator,
            compiler=compiler,
        )

        assert res.success is True
        assert res.workflow_id == "n8n_wf_777"
        assert res.is_active is False
        assert draft.status == "deployed"
        assert conv.metadata_json["deployment"]["workflow_id"] == "n8n_wf_777"
        assert conv.metadata_json["deployment"]["is_active"] is False


@pytest.mark.asyncio
async def test_deploy_workflow_duplicate_idempotency_returns_existing(sample_valid_ir):
    """Duplicate deployment call with same idempotency token returns existing result without recreating."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(
        id=conv_id,
        title="Test Flow",
        metadata_json={
            "deployment": {
                "workflow_id": "n8n_wf_777",
                "workflow_name": "Test Automation",
                "workflow_url": "http://localhost:5678/workflow/n8n_wf_777",
                "revision_number": 1,
                "idempotency_token": "tok_123",
            }
        },
    )
    draft = WorkflowDraft(id=str(uuid.uuid4()), conversation_id=conv_id, title="Test Flow", status="deployed")
    rev = WorkflowRevision(id=str(uuid.uuid4()), draft_id=draft.id, revision_number=1, workflow_ir=sample_valid_ir)

    session = MockRevisionSession(conversation=conv, draft=draft, revisions=[rev])
    registry = NodeRegistry()
    validator = WorkflowValidator(registry=registry)
    evaluator = WorkflowReadinessEvaluator(registry=registry, validator=validator)
    compiler = WorkflowCompiler()

    req = DeployWorkflowRequest(expected_revision_number=1, idempotency_token="tok_123")
    res = await deploy_draft_workflow(
        conversation_id=conv_id,
        payload=req,
        db=session,
        evaluator=evaluator,
        compiler=compiler,
    )

    assert res.success is True
    assert res.workflow_id == "n8n_wf_777"
    assert "already deployed" in res.message


@pytest.mark.asyncio
async def test_deploy_workflow_timeout_raises_gateway_timeout(sample_valid_ir):
    """Timeout during deployment raises HTTP 504 with uncertain outcome explanation."""
    conv_id = str(uuid.uuid4())
    conv = Conversation(id=conv_id, title="Test Flow")
    draft = WorkflowDraft(id=str(uuid.uuid4()), conversation_id=conv_id, title="Test Flow")
    rev = WorkflowRevision(id=str(uuid.uuid4()), draft_id=draft.id, revision_number=1, workflow_ir=sample_valid_ir)

    session = MockRevisionSession(conversation=conv, draft=draft, revisions=[rev])
    registry = NodeRegistry()
    validator = WorkflowValidator(registry=registry)
    evaluator = WorkflowReadinessEvaluator(registry=registry, validator=validator)
    compiler = WorkflowCompiler()

    with patch.object(N8nClient, "check_connection", new_callable=AsyncMock) as mock_check, \
         patch.object(N8nClient, "create_workflow", new_callable=AsyncMock) as mock_create:
        mock_check.return_value = N8nStatusResponse(status=N8nConnectionState.CONNECTED, message="Connected")
        mock_create.side_effect = N8nDeploymentTimeoutError("Deployment timed out after 10s. Outcome is uncertain.")

        req = DeployWorkflowRequest(expected_revision_number=1)
        with pytest.raises(HTTPException) as exc:
            await deploy_draft_workflow(
                conversation_id=conv_id,
                payload=req,
                db=session,
                evaluator=evaluator,
                compiler=compiler,
            )
        assert exc.value.status_code == 504
        assert "Outcome is uncertain" in exc.value.detail
