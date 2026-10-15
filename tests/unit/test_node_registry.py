"""Unit tests for the n8n Node Registry service."""
import pytest
from backend.app.services.node_registry import NodeRegistry, NodeDefinition


@pytest.fixture
def real_registry() -> NodeRegistry:
    """Fixture providing NodeRegistry backed by the verified n8n 2.42.6 catalog."""
    return NodeRegistry()


@pytest.fixture
def mocked_registry() -> NodeRegistry:
    """Fixture providing isolated in-memory NodeRegistry for edge cases."""
    mock_data = {
        "provenance": {
            "n8n_version": "2.42.6-mock",
            "source": "unit-test-mock",
            "total_nodes": 2,
        },
        "nodes": {
            "n8n-nodes-base.mockAction": {
                "name": "mockAction",
                "canonical_name": "n8n-nodes-base.mockAction",
                "displayName": "Mock Action Node",
                "description": "Mock node for testing parameter validation",
                "group": ["transform"],
                "is_trigger": False,
                "default_version": 1.0,
                "supported_versions": [1.0, 2.0],
                "inputs": ["main"],
                "outputs": ["main"],
                "credentials": [{"name": "mockApiKey", "required": True}],
                "properties": [
                    {
                        "name": "targetUrl",
                        "displayName": "Target URL",
                        "type": "string",
                        "default": "",
                        "required": True,
                    },
                    {
                        "name": "retryCount",
                        "displayName": "Retry Count",
                        "type": "number",
                        "default": 3,
                        "required": False,
                    },
                    {
                        "name": "httpMethod",
                        "displayName": "HTTP Method",
                        "type": "options",
                        "default": "GET",
                        "required": False,
                        "options": [
                            {"name": "GET", "value": "GET"},
                            {"name": "POST", "value": "POST"},
                        ],
                    },
                ],
                "operations": ["fetch", "update"],
                "resources": ["item"],
                "version_details": {},
            },
            "n8n-nodes-base.mockTrigger": {
                "name": "mockTrigger",
                "canonical_name": "n8n-nodes-base.mockTrigger",
                "displayName": "Mock Trigger Node",
                "description": "Mock trigger entrypoint",
                "group": ["trigger"],
                "is_trigger": True,
                "default_version": 1.0,
                "supported_versions": [1.0],
                "inputs": [],
                "outputs": ["main"],
                "credentials": [],
                "properties": [],
                "operations": [],
                "resources": [],
                "version_details": {},
            },
        },
    }
    return NodeRegistry.from_dict(mock_data)


def test_registry_provenance_and_indexing(real_registry: NodeRegistry):
    """Verifies that the catalog loaded real nodes and recorded exact provenance."""
    assert len(real_registry) >= 400
    prov = real_registry.provenance
    assert prov["n8n_version"] == "2.42.6"
    assert prov["source"] == "n8n-nodes-base"
    assert prov["total_nodes"] == 444


def test_canonical_and_short_name_lookup(real_registry: NodeRegistry):
    """Verifies lookup via canonical type ID and short name case-insensitively."""
    node_canon = real_registry.get_node("n8n-nodes-base.httpRequest")
    assert node_canon is not None
    assert node_canon.name == "httpRequest"
    assert node_canon.canonical_name == "n8n-nodes-base.httpRequest"

    # Case-insensitive canonical lookup
    node_upper = real_registry.get_node("N8N-NODES-BASE.HTTPREQUEST")
    assert node_upper is not None
    assert node_upper.canonical_name == node_canon.canonical_name

    # Short name lookup
    node_short = real_registry.get_node("httprequest")
    assert node_short is not None
    assert node_short.canonical_name == node_canon.canonical_name


def test_version_support_verification(real_registry: NodeRegistry):
    """Verifies version compatibility checks for versioned and unversioned nodes."""
    # 'If' node has versions [1, 2, 2.1, 2.2, 2.3] in n8n 2.42.6
    assert real_registry.is_version_supported("n8n-nodes-base.if", 2.3) is True
    assert real_registry.is_version_supported("n8n-nodes-base.if", 1.0) is True
    assert real_registry.is_version_supported("n8n-nodes-base.if", 99.0) is False

    # Non-existent node
    assert real_registry.is_version_supported("n8n-nodes-base.nonExistentNode", 1.0) is False


def test_operation_support_verification(real_registry: NodeRegistry):
    """Verifies operation discovery and validation."""
    slack_node = real_registry.get_node("n8n-nodes-base.slack")
    assert slack_node is not None
    assert "post" in slack_node.operations or "sendAndWait" in slack_node.operations

    assert real_registry.is_operation_supported("n8n-nodes-base.slack", "post") is True
    assert real_registry.is_operation_supported("n8n-nodes-base.slack", "unsupported_alien_op") is False


def test_required_parameters_introspection(real_registry: NodeRegistry):
    """Verifies introspection of required node parameters."""
    req_params = real_registry.get_required_parameters("n8n-nodes-base.httpRequest")
    param_names = [p.name for p in req_params]
    assert "url" in param_names


def test_faceted_search(real_registry: NodeRegistry):
    """Verifies multi-attribute filtering (keyword, trigger status, category)."""
    # Keyword search
    webhook_matches = real_registry.search("webhook", limit=10)
    assert len(webhook_matches) > 0
    assert any(m.name == "webhook" for m in webhook_matches)

    # Filter trigger nodes only
    triggers = real_registry.search("", is_trigger=True, limit=20)
    assert len(triggers) > 0
    assert all(t.is_trigger for t in triggers)

    # Filter category 'transform'
    transforms = real_registry.search("", category="transform", limit=20)
    assert len(transforms) > 0
    assert all(any(g.lower() == "transform" for g in t.group) for t in transforms)


def test_missing_and_unsupported_node_reporting(real_registry: NodeRegistry):
    """Verifies clean reporting when an unrecognized node is queried."""
    assert real_registry.is_node_supported("n8n-nodes-base.imaginaryNodeXYZ") is False
    assert real_registry.get_node("n8n-nodes-base.imaginaryNodeXYZ") is None
    assert real_registry.get_required_parameters("n8n-nodes-base.imaginaryNodeXYZ") == []


def test_mocked_registry_parameter_options(mocked_registry: NodeRegistry):
    """Verifies parameter options and constraints using a mocked fixture."""
    node = mocked_registry.get_node("n8n-nodes-base.mockAction")
    assert node is not None
    assert len(node.properties) == 3

    param = node.get_parameter("httpMethod")
    assert param is not None
    assert param.type == "options"
    assert param.allowed_values == ["GET", "POST"]

    target_url_param = node.get_parameter("targetUrl")
    assert target_url_param is not None
    assert target_url_param.required is True
