"""Unit tests for the node catalog search endpoint and registry integration."""
import pytest
from backend.app.api.v1.conversations import search_nodes
from backend.app.security.auth import UserContext
from backend.app.services.node_registry import NodeRegistry


@pytest.mark.asyncio
async def test_search_nodes_by_query():
    """Verify search_nodes returns verified nodes matching query."""
    registry = NodeRegistry()
    user = UserContext(user_id="test_user", is_authenticated=True, auth_method="local_trust")

    results = await search_nodes(
        q="telegram",
        category=None,
        is_trigger=None,
        limit=10,
        node_registry=registry,
        current_user=user,
    )

    assert len(results) > 0
    telegram_node = next((n for n in results if "telegram" in n["name"].lower()), None)
    assert telegram_node is not None
    assert "telegram" in telegram_node["canonical_name"].lower()
    assert "name" in telegram_node
    assert "canonical_name" in telegram_node
    assert "display_name" in telegram_node


@pytest.mark.asyncio
async def test_search_nodes_trigger_filter():
    """Verify is_trigger filter strictly filters trigger nodes."""
    registry = NodeRegistry()
    user = UserContext(user_id="test_user", is_authenticated=True, auth_method="local_trust")

    trigger_results = await search_nodes(
        q="",
        category=None,
        is_trigger=True,
        limit=20,
        node_registry=registry,
        current_user=user,
    )

    assert len(trigger_results) > 0
    for node in trigger_results:
        assert node["is_trigger"] is True


@pytest.mark.asyncio
async def test_search_nodes_limit_and_structure():
    """Verify limit parameter caps the returned list and fields conform to schema."""
    registry = NodeRegistry()
    user = UserContext(user_id="test_user", is_authenticated=True, auth_method="local_trust")

    results = await search_nodes(
        q="",
        category=None,
        is_trigger=None,
        limit=5,
        node_registry=registry,
        current_user=user,
    )

    assert len(results) == 5
    for item in results:
        assert isinstance(item["canonical_name"], str)
        assert isinstance(item["display_name"], str)
        assert isinstance(item["is_trigger"], bool)
        assert isinstance(item["credentials"], list)
