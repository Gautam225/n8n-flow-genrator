"""Integration tests for the Conversation API with real PostgreSQL persistence.

Per strict architectural constraints:
- PostgreSQL is mandatory. Never use SQLite.
- Tests exercise real FastAPI routes with real PostgreSQL sessions.
- Bounded mocks are used only for LLM completion to avoid external token costs and non-determinism.
"""
import uuid
import pytest
import httpx
from httpx import ASGITransport

from backend.app.main import app
from backend.app.db.session import check_database_connection, close_database_engine
from backend.app.api.v1.conversations import get_orchestrator
from backend.app.orchestrator.engine import WorkflowOrchestrator
from backend.app.orchestrator.schemas import OrchestratorTurnResult, ClarificationPlan, ClarificationQuestion, ClarificationOption
from backend.app.orchestrator.state_machine import ConversationState


async def _ensure_postgres():
    """Ensure PostgreSQL is accessible before running integration tests."""
    is_connected, message = await check_database_connection()
    if not is_connected:
        pytest.skip(f"PostgreSQL integration test skipped (database unreachable): {message}")


@pytest.mark.asyncio
async def test_conversation_lifecycle_crud():
    """Test full conversation CRUD lifecycle in real PostgreSQL database."""
    await _ensure_postgres()
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Create conversation
            create_res = await client.post(
                "/api/v1/conversations",
                json={"title": "Test Integration Flow"},
            )
            assert create_res.status_code == 201, create_res.text
            conv_data = create_res.json()
            conv_id = conv_data["conversation_id"]
            assert conv_data["title"] == "Test Integration Flow"
            assert conv_data["state"] == "planning"

            # 2. List conversations
            list_res = await client.get("/api/v1/conversations")
            assert list_res.status_code == 200
            items = list_res.json()
            assert any(c["id"] == conv_id for c in items)

            # 3. Retrieve conversation detail
            get_res = await client.get(f"/api/v1/conversations/{conv_id}")
            assert get_res.status_code == 200
            detail = get_res.json()
            assert detail["id"] == conv_id
            assert detail["title"] == "Test Integration Flow"
            assert len(detail["messages"]) == 0

            # 4. Rename conversation
            patch_res = await client.patch(
                f"/api/v1/conversations/{conv_id}",
                json={"title": "Renamed Integration Flow"},
            )
            assert patch_res.status_code == 200
            assert patch_res.json()["title"] == "Renamed Integration Flow"

            # 5. Delete conversation
            del_res = await client.delete(f"/api/v1/conversations/{conv_id}")
            assert del_res.status_code == 204

            # 6. Verify 404 after deletion
            get_deleted = await client.get(f"/api/v1/conversations/{conv_id}")
            assert get_deleted.status_code == 404
    finally:
        await close_database_engine()


@pytest.mark.asyncio
async def test_conversation_message_turn_with_orchestrator():
    """Test sending user messages and receiving orchestrator turn responses."""
    await _ensure_postgres()
    try:
        # Create a mock orchestrator to test the route logic deterministically
        class MockOrchestrator(WorkflowOrchestrator):
            async def execute_turn(self, conversation_id, user_message_text, db, selected_options=None):
                from backend.app.models.conversation import ConversationMessage
                # Simulate saving messages in DB
                user_msg = ConversationMessage(
                    id=str(uuid.uuid4()),
                    conversation_id=conversation_id,
                    role="user",
                    content=user_message_text,
                )
                asst_msg = ConversationMessage(
                    id=str(uuid.uuid4()),
                    conversation_id=conversation_id,
                    role="assistant",
                    content="Which trigger would you prefer?",
                )
                db.add_all([user_msg, asst_msg])
                await db.commit()

                return OrchestratorTurnResult(
                    conversation_id=conversation_id,
                    state=ConversationState.CLARIFYING,
                    assistant_message="Which trigger would you prefer?",
                    clarification=ClarificationPlan(
                        has_ambiguities=True,
                        questions=[
                            ClarificationQuestion(
                                id="q_trigger",
                                field_key="trigger_type",
                                question="Which trigger would you like to use?",
                                options=[
                                    ClarificationOption(value="webhook", label="Webhook", description="Trigger via HTTP POST"),
                                    ClarificationOption(value="schedule", label="Schedule", description="Trigger periodically"),
                                ],
                            )
                        ],
                    ),
                )

        app.dependency_overrides[get_orchestrator] = lambda: MockOrchestrator(llm_manager=None)

        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Create conversation
            create_res = await client.post("/api/v1/conversations", json={"title": "Message Turn Test"})
            assert create_res.status_code == 201
            conv_id = create_res.json()["conversation_id"]

            try:
                # Send message
                msg_res = await client.post(
                    f"/api/v1/conversations/{conv_id}/messages",
                    json={"content": "Build me a workflow that alerts me on errors"},
                )
                assert msg_res.status_code == 200, msg_res.text
                result = msg_res.json()
                assert result["state"] == "clarifying"
                assert "Which trigger" in result["assistant_message"]
                assert result["clarification"]["has_ambiguities"] is True
                assert len(result["clarification"]["questions"]) == 1

                # Fetch history and verify chronological message order
                detail_res = await client.get(f"/api/v1/conversations/{conv_id}")
                messages = detail_res.json()["messages"]
                assert len(messages) == 2
                assert messages[0]["role"] == "user"
                assert messages[1]["role"] == "assistant"
            finally:
                # Clean up
                await client.delete(f"/api/v1/conversations/{conv_id}")
                app.dependency_overrides.clear()
    finally:
        await close_database_engine()


@pytest.mark.asyncio
async def test_conversation_validation_and_safety():
    """Verify input validation, 404 handling, and safety guards."""
    await _ensure_postgres()
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Invalid conversation UUID format or non-existent conversation
            random_id = str(uuid.uuid4())
            res_404 = await client.get(f"/api/v1/conversations/{random_id}")
            assert res_404.status_code == 404

            # Empty message content
            bad_msg = await client.post(f"/api/v1/conversations/{random_id}/messages", json={"content": ""})
            assert bad_msg.status_code == 422

            # Message to non-existent conversation
            not_found_msg = await client.post(f"/api/v1/conversations/{random_id}/messages", json={"content": "Hello"})
            assert not_found_msg.status_code == 404
    finally:
        await close_database_engine()


@pytest.mark.asyncio
async def test_draft_revisions_postgres_persistence_and_concurrency():
    """Verify draft revision persistence, sequential revision numbers, and 409 concurrency guards in PostgreSQL."""
    await _ensure_postgres()
    try:
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Create conversation
            conv_res = await client.post("/api/v1/conversations", json={"title": "Draft Editing Pipeline"})
            assert conv_res.status_code == 201
            conv_id = conv_res.json()["conversation_id"]

            try:
                valid_ir = {
                    "id": "wf_rev_test",
                    "name": "Integration Revision Test",
                    "nodes": [
                        {
                            "id": "node_schedule",
                            "name": "Hourly Schedule",
                            "node_type": "n8n-nodes-base.scheduleTrigger",
                            "type_version": 1.2,
                        },
                        {
                            "id": "node_http",
                            "name": "Fetch Records",
                            "node_type": "n8n-nodes-base.httpRequest",
                            "type_version": 4.2,
                            "parameters": {"url": "https://api.example.com/items", "method": "GET"},
                        },
                    ],
                    "edges": [
                        {
                            "source_id": "node_schedule",
                            "target_id": "node_http",
                            "connection_type": "main",
                            "source_output_index": 0,
                            "target_input_index": 0,
                        }
                    ],
                }

                # 2. Validate without persisting
                val_res = await client.post(f"/api/v1/conversations/{conv_id}/draft/validate", json={"workflow_ir": valid_ir})
                assert val_res.status_code == 200
                val_data = val_res.json()
                assert val_data["is_valid"] is True
                assert val_data["compiled_json"] is not None

                # 3. Save Revision 1
                save_res1 = await client.post(
                    f"/api/v1/conversations/{conv_id}/draft/revisions",
                    json={"workflow_ir": valid_ir, "expected_revision_number": 0},
                )
                assert save_res1.status_code == 201
                rev1_data = save_res1.json()
                assert rev1_data["revision_number"] == 1
                assert rev1_data["is_valid"] is True
                assert rev1_data["status"] == "ready"
                assert rev1_data["compiled_json"] is not None

                # 4. Save Revision 2 with updated parameter
                valid_ir["nodes"][1]["parameters"]["url"] = "https://api.example.com/items_v2"
                save_res2 = await client.post(
                    f"/api/v1/conversations/{conv_id}/draft/revisions",
                    json={"workflow_ir": valid_ir, "expected_revision_number": 1},
                )
                assert save_res2.status_code == 201
                rev2_data = save_res2.json()
                assert rev2_data["revision_number"] == 2
                assert rev2_data["is_valid"] is True

                # 5. Stale Revision Conflict (Optimistic Concurrency Control)
                conflict_res = await client.post(
                    f"/api/v1/conversations/{conv_id}/draft/revisions",
                    json={"workflow_ir": valid_ir, "expected_revision_number": 1},  # Current is 2, expecting 1
                )
                assert conflict_res.status_code == 409
                assert "Stale revision conflict" in conflict_res.json()["detail"]

                # 6. List revisions in PostgreSQL
                list_revs = await client.get(f"/api/v1/conversations/{conv_id}/draft/revisions")
                assert list_revs.status_code == 200
                revs_list = list_revs.json()
                assert len(revs_list) == 2
                assert revs_list[0]["revision_number"] == 2
                assert revs_list[1]["revision_number"] == 1

                # 7. Get revision detail
                detail_rev1 = await client.get(f"/api/v1/conversations/{conv_id}/draft/revisions/1")
                assert detail_rev1.status_code == 200
                assert detail_rev1.json()["revision_number"] == 1
                assert detail_rev1.json()["workflow_ir"]["nodes"][1]["parameters"]["url"] == "https://api.example.com/items"

                # 8. Save invalid revision (missing required parameters)
                invalid_ir = {
                    "id": "wf_invalid",
                    "name": "Invalid IR",
                    "nodes": [
                        {
                            "id": "node_http_bad",
                            "name": "Bad HTTP",
                            "node_type": "n8n-nodes-base.httpRequest",
                            "type_version": 4.2,
                            "parameters": {},  # missing 'url'
                        }
                    ],
                    "edges": [],
                }
                save_invalid_res = await client.post(
                    f"/api/v1/conversations/{conv_id}/draft/revisions",
                    json={"workflow_ir": invalid_ir, "expected_revision_number": 2},
                )
                assert save_invalid_res.status_code == 201
                invalid_data = save_invalid_res.json()
                assert invalid_data["revision_number"] == 3
                assert invalid_data["is_valid"] is False
                assert invalid_data["status"] == "invalid"
                assert invalid_data["compiled_json"] is None

                # Invariant: Conversation state must not be marked 'ready'
                conv_detail = await client.get(f"/api/v1/conversations/{conv_id}")
                assert conv_detail.json()["state"] != "ready"

                # 9. Test Readiness Evaluation API Endpoint
                readiness_res = await client.post(
                    f"/api/v1/conversations/{conv_id}/draft/readiness",
                    json={"workflow_ir": valid_ir},
                )
                assert readiness_res.status_code == 200
                readiness_data = readiness_res.json()
                assert readiness_data["overall_status"] in ("ready", "needs_attention")
                assert "test_plan" in readiness_data
                assert readiness_data["test_plan"]["can_run_local_dry_run"] is True

                # 10. Test Safe Simulation API Endpoint
                sim_res = await client.post(
                    f"/api/v1/conversations/{conv_id}/draft/simulate",
                    json={"workflow_ir": valid_ir},
                )
                assert sim_res.status_code == 200
                sim_data = sim_res.json()
                assert sim_data["success"] is True
                assert sim_data["execution_type"] == "deterministic_static_dry_run"
                assert sim_data["passed_nodes"] == 2
                assert "No external services" in sim_data["disclaimer"]

                # 11. Test Readiness with Invalid IR
                bad_readiness_res = await client.post(
                    f"/api/v1/conversations/{conv_id}/draft/readiness",
                    json={"workflow_ir": invalid_ir},
                )
                assert bad_readiness_res.status_code == 200
                bad_readiness_data = bad_readiness_res.json()
                assert bad_readiness_data["overall_status"] == "blocked"
                assert bad_readiness_data["is_deployable_to_n8n"] is False

            finally:
                # 12. Cleanup conversation (cascades draft and revisions)
                await client.delete(f"/api/v1/conversations/{conv_id}")
    finally:
        await close_database_engine()


@pytest.mark.asyncio
async def test_conversation_retry_and_concurrency_guards():
    """Verify retry endpoint reuses conversation, passes original prompt without duplicating user messages, and guards against concurrency."""
    await _ensure_postgres()
    try:
        from unittest.mock import AsyncMock, MagicMock
        mock_orch = MagicMock(spec=WorkflowOrchestrator)

        # First call fails
        mock_orch.execute_turn = AsyncMock(
            return_value=OrchestratorTurnResult(
                conversation_id="pending",
                state=ConversationState.FAILED,
                assistant_message="Failed to complete workflow planning: All LLM providers unavailable.",
                original_prompt="Sync Postgres to Slack every hour",
                error_details={"category": "RATE_LIMIT_EXCEEDED"},
            )
        )
        app.dependency_overrides[get_orchestrator] = lambda: mock_orch

        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Create conversation with initial prompt
            create_res = await client.post(
                "/api/v1/conversations",
                json={
                    "title": "Hourly Sync",
                    "initial_prompt": "Sync Postgres to Slack every hour",
                },
            )
            assert create_res.status_code == 201
            conv_id = create_res.json()["conversation_id"]

            try:
                # Verify conversation has 1 initial user message persisted before turn execution
                detail_1 = await client.get(f"/api/v1/conversations/{conv_id}")
                msgs_1 = detail_1.json()["messages"]
                assert len(msgs_1) == 1
                assert msgs_1[0]["role"] == "user"
                assert msgs_1[0]["content"] == "Sync Postgres to Slack every hour"

                # 2. Test Concurrency Guard: Orchestrator raises already in progress
                mock_orch.execute_turn = AsyncMock(side_effect=ValueError("A workflow generation request is already in progress for conversation"))
                conflict_res = await client.post(
                    f"/api/v1/conversations/{conv_id}/messages",
                    json={"content": "Another message while generating"},
                )
                assert conflict_res.status_code == 409
                assert "already in progress" in conflict_res.json()["detail"]

                # 3. Test Retry Endpoint: Retry succeeds
                mock_orch.execute_turn = AsyncMock(
                    return_value=OrchestratorTurnResult(
                        conversation_id=conv_id,
                        state=ConversationState.CLARIFYING,
                        assistant_message="Which Slack channel should receive the alerts?",
                        original_prompt="Sync Postgres to Slack every hour",
                        clarification=ClarificationPlan(
                            has_ambiguities=True,
                            questions=[
                                ClarificationQuestion(
                                    id="slack_channel",
                                    question="Which Slack channel?",
                                    field_key="channel",
                                    is_required=True,
                                    options=[ClarificationOption(label="#general", value="#general")],
                                )
                            ],
                        ),
                    )
                )

                retry_res = await client.post(f"/api/v1/conversations/{conv_id}/retry")
                assert retry_res.status_code == 200
                retry_data = retry_res.json()
                assert retry_data["state"] == "clarifying"

                # Verify mock_orch was called with original_prompt and skip_user_message_persistence=True
                mock_orch.execute_turn.assert_called_once()
                call_kwargs = mock_orch.execute_turn.call_args.kwargs
                assert call_kwargs["conversation_id"] == conv_id
                assert call_kwargs["user_message_text"] == "Sync Postgres to Slack every hour"
                assert call_kwargs["is_retry"] is True
                assert call_kwargs["skip_user_message_persistence"] is True

                # Verify user messages were not duplicated in database
                detail_2 = await client.get(f"/api/v1/conversations/{conv_id}")
                user_msgs = [m for m in detail_2.json()["messages"] if m["role"] == "user"]
                assert len(user_msgs) == 1
            finally:
                await client.delete(f"/api/v1/conversations/{conv_id}")
                app.dependency_overrides.clear()
    finally:
        await close_database_engine()


