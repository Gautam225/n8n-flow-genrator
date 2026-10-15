"""n8n Node Registry providing schema introspection and capability discovery.

This module indexes verified n8n node definitions extracted directly from the
source-of-truth running n8n package (`n8n-nodes-base` v2.42.6). It provides
catalog lookups, version compatibility checks, parameter definitions, required
field introspection, operation discovery, and fuzzy/faceted search.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from pydantic import BaseModel, ConfigDict, Field

STOP_WORDS: Set[str] = {
    "when", "i", "an", "a", "the", "on", "in", "to", "for", "me", "is", "it",
    "at", "by", "of", "and", "or", "with", "from", "my", "then", "into", "as",
    "be", "this", "that", "you", "we", "your", "our", "all", "any"
}


class NodeParameterOption(BaseModel):
    """An option choice for select/enum parameters."""
    model_config = ConfigDict(frozen=True)

    name: str
    value: Any
    description: Optional[str] = None


class NodeParameterDefinition(BaseModel):
    """Definition of an individual node parameter or configuration property."""
    model_config = ConfigDict(frozen=True)

    name: str
    display_name: str
    type: str
    default: Any = None
    required: bool = False
    description: Optional[str] = None
    options: List[NodeParameterOption] = Field(default_factory=list)
    display_options: Optional[Dict[str, Any]] = None

    @property
    def allowed_values(self) -> List[Any]:
        """Returns the list of allowed primitive values if options are defined."""
        return [opt.value for opt in self.options]


class NodeCredentialRequirement(BaseModel):
    """Credential type required or supported by a node."""
    model_config = ConfigDict(frozen=True)

    name: str
    required: bool = False


class NodeDefinition(BaseModel):
    """Normalized schema representation of an n8n node type."""
    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Short identifier, e.g. 'httpRequest'")
    canonical_name: str = Field(description="Fully qualified n8n type, e.g. 'n8n-nodes-base.httpRequest'")
    display_name: str = Field(description="Human-readable title, e.g. 'HTTP Request'")
    description: str = Field(default="", description="High-level description of node functionality")
    group: List[str] = Field(default_factory=list, description="Category classifications (e.g. ['transform'])")
    is_trigger: bool = Field(default=False, description="Whether node serves as an execution entrypoint")
    default_version: float = Field(default=1.0, description="Recommended default typeVersion")
    supported_versions: List[float] = Field(default_factory=list, description="All valid typeVersions")
    inputs: Any = Field(default_factory=list, description="Declared input sockets or 'dynamic'")
    outputs: Any = Field(default_factory=list, description="Declared output sockets or 'dynamic'")
    credentials: List[NodeCredentialRequirement] = Field(default_factory=list)
    properties: List[NodeParameterDefinition] = Field(default_factory=list)
    operations: List[str] = Field(default_factory=list, description="Supported actions/operations")
    resources: List[str] = Field(default_factory=list, description="Supported resource types if applicable")
    version_details: Dict[str, Any] = Field(default_factory=dict, description="Version-specific schemas")

    @property
    def output_count(self) -> Optional[int]:
        """Returns static output count if statically known, or None if dynamic."""
        if isinstance(self.outputs, list):
            return len(self.outputs)
        return None

    @property
    def input_count(self) -> Optional[int]:
        """Returns static input count if statically known, or None if dynamic."""
        if isinstance(self.inputs, list):
            return len(self.inputs)
        return None

    def get_parameter(self, param_name: str, version: Optional[float] = None) -> Optional[NodeParameterDefinition]:
        """Retrieves parameter definition by name, optionally resolving version-specific override."""
        props = self.get_properties(version=version)
        for p in props:
            if p.name == param_name:
                return p
        return None

    def get_properties(self, version: Optional[float] = None) -> List[NodeParameterDefinition]:
        """Returns properties for the given version or node default."""
        if version is not None and str(version) in self.version_details:
            v_props = self.version_details[str(version)].get("properties", [])
            return [
                NodeParameterDefinition(
                    name=p.get("name", ""),
                    display_name=p.get("displayName", p.get("name", "")),
                    type=p.get("type", "string"),
                    default=p.get("default"),
                    required=bool(p.get("required", False)),
                    description=p.get("description"),
                    options=[
                        NodeParameterOption(
                            name=o.get("name", str(o.get("value", ""))),
                            value=o.get("value", o.get("name")),
                            description=o.get("description")
                        )
                        for o in p.get("options", [])
                        if isinstance(o, dict)
                    ],
                    display_options=p.get("displayOptions")
                )
                for p in v_props
            ]
        return self.properties

    def get_operations(self, version: Optional[float] = None) -> List[str]:
        """Returns supported operations for the given version or node default."""
        if version is not None and str(version) in self.version_details:
            return self.version_details[str(version)].get("operations", [])
        return self.operations

    def get_expected_credentials(
        self,
        parameters: Optional[Dict[str, Any]] = None,
        current_credentials: Optional[Dict[str, Any]] = None,
    ) -> List[NodeCredentialRequirement]:
        """Resolves active credential requirements based on parameters and authentication mode.

        Handles alternative authentication modes (e.g. OAuth2 vs Service Account for Google Sheets)
        rather than incorrectly requiring all credentials in the catalog simultaneously.
        """
        if not self.credentials:
            return []
        # If current_credentials already has one of the supported credentials, use that one
        if current_credentials:
            matching = [c for c in self.credentials if c.name in current_credentials]
            if matching:
                return matching

        params = parameters or {}
        auth = params.get("authentication")
        if not auth:
            # Check default value for authentication property
            for p in self.properties:
                if p.name == "authentication" and p.default:
                    auth = p.default
                    break

        clean_name = self.name.replace("n8n-nodes-base.", "")
        if clean_name == "httpRequest":
            if not auth or auth == "none":
                return []
            return [c for c in self.credentials if c.name == auth]

        if len(self.credentials) == 1:
            return [c for c in self.credentials if c.required]

        # Node-specific mappings for known alternative credentials
        clean_name = self.name.replace("n8n-nodes-base.", "")
        if clean_name == "googleSheetsTrigger":
            if auth == "serviceAccount":
                return [c for c in self.credentials if c.name == "googleApi"]
            # Default or triggerOAuth2
            return [c for c in self.credentials if c.name == "googleSheetsTriggerOAuth2Api"]

        if clean_name == "googleSheets":
            if auth == "serviceAccount":
                return [c for c in self.credentials if c.name == "googleApi"]
            return [c for c in self.credentials if c.name == "googleSheetsOAuth2Api"]

        if clean_name in ("gmail", "gmailTrigger"):
            if auth == "serviceAccount":
                return [c for c in self.credentials if c.name == "googleApi"]
            return [c for c in self.credentials if c.name == "gmailOAuth2"]

        if clean_name == "slack":
            if auth == "oAuth2":
                return [c for c in self.credentials if c.name == "slackOAuth2Api"]
            return [c for c in self.credentials if c.name == "slackApi"]

        if clean_name in ("microsoftOutlook", "microsoftOutlookTrigger"):
            if auth and any(c.name == auth for c in self.credentials):
                return [c for c in self.credentials if c.name == auth]
            return [c for c in self.credentials if c.name == "microsoftOutlookOAuth2Api"]

        if auth:
            direct_match = [c for c in self.credentials if c.name == auth]
            if direct_match:
                return direct_match
            if auth in ("oAuth2", "triggerOAuth2"):
                oauth_creds = [c for c in self.credentials if "oauth" in c.name.lower()]
                if oauth_creds:
                    return [oauth_creds[0]]
            if auth == "serviceAccount":
                sa_creds = [c for c in self.credentials if "googleapi" in c.name.lower() or "service" in c.name.lower()]
                if sa_creds:
                    return [sa_creds[0]]
            if auth in ("apiKey", "accessToken", "apiToken"):
                api_creds = [c for c in self.credentials if c.name.endswith("Api") and "oauth" not in c.name.lower()]
                if api_creds:
                    return [api_creds[0]]

        # Fallback: prefer OAuth2 or the first required credential
        oauth_creds = [c for c in self.credentials if "oauth" in c.name.lower() and c.required]
        if oauth_creds:
            return [oauth_creds[0]]
        req_creds = [c for c in self.credentials if c.required]
        if req_creds:
            return [req_creds[0]]
        return [self.credentials[0]]


class NodeRegistry:
    """Registry providing indexing, searching, and schema inspection for n8n nodes."""

    DEFAULT_CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "node_catalog.json"
    _DEFAULT_INDEXES: Optional[Tuple[Dict[str, NodeDefinition], Dict[str, NodeDefinition], Dict[str, Any]]] = None
    _SEARCH_CACHE: Dict[str, List[NodeDefinition]] = {}
    _CACHE_MAX_SIZE: int = 256

    def __init__(self, catalog_data: Optional[Dict[str, Any]] = None, catalog_path: Optional[Union[Path, str]] = None):
        """Initializes the registry from in-memory dict or catalog file with process-level singleton caching."""
        self._nodes_by_canonical: Dict[str, NodeDefinition] = {}
        self._nodes_by_short_name: Dict[str, NodeDefinition] = {}
        self._provenance: Dict[str, Any] = {}

        if catalog_data is not None:
            self._load_from_dict(catalog_data)
        elif catalog_path is not None:
            path = Path(catalog_path)
            if path.exists():
                self._load_from_file(path)
            else:
                self._provenance = {"n8n_version": "unknown", "source": "empty", "loaded_nodes": 0}
        else:
            # Default catalog path: use process singleton cache
            if NodeRegistry._DEFAULT_INDEXES is not None:
                self._nodes_by_canonical, self._nodes_by_short_name, self._provenance = NodeRegistry._DEFAULT_INDEXES
                return

            if self.DEFAULT_CATALOG_PATH.exists():
                self._load_from_file(self.DEFAULT_CATALOG_PATH)
                NodeRegistry._DEFAULT_INDEXES = (
                    dict(self._nodes_by_canonical),
                    dict(self._nodes_by_short_name),
                    dict(self._provenance),
                )
            else:
                self._provenance = {"n8n_version": "unknown", "source": "empty", "loaded_nodes": 0}

    @classmethod
    def invalidate_cache(cls) -> None:
        """Clears process singleton catalog and search caches."""
        cls._DEFAULT_INDEXES = None
        cls._SEARCH_CACHE.clear()

    def _load_from_file(self, path: Path) -> None:
        """Loads and indexes definitions from a JSON catalog file."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._load_from_dict(data)

    def _load_from_dict(self, data: Dict[str, Any]) -> None:
        """Parses dictionary payload into NodeDefinition instances."""
        self._provenance = data.get("provenance", {})
        raw_nodes = data.get("nodes", {})

        for raw_key, raw_node in raw_nodes.items():
            credentials = [
                NodeCredentialRequirement(
                    name=c.get("name", ""),
                    required=bool(c.get("required", False))
                )
                for c in raw_node.get("credentials", [])
            ]

            properties = [
                NodeParameterDefinition(
                    name=p.get("name", ""),
                    display_name=p.get("displayName", p.get("name", "")),
                    type=p.get("type", "string"),
                    default=p.get("default"),
                    required=bool(p.get("required", False)),
                    description=p.get("description"),
                    options=[
                        NodeParameterOption(
                            name=o.get("name", str(o.get("value", ""))),
                            value=o.get("value", o.get("name")),
                            description=o.get("description")
                        )
                        for o in p.get("options", [])
                        if isinstance(o, dict)
                    ],
                    display_options=p.get("displayOptions")
                )
                for p in raw_node.get("properties", [])
            ]

            supported_versions = [
                float(v) for v in raw_node.get("supported_versions", [1.0])
                if isinstance(v, (int, float)) or (isinstance(v, str) and v.replace(".", "", 1).isdigit())
            ]

            node_def = NodeDefinition(
                name=raw_node.get("name", ""),
                canonical_name=raw_node.get("canonical_name", raw_key),
                display_name=raw_node.get("displayName", raw_node.get("name", "")),
                description=raw_node.get("description", ""),
                group=raw_node.get("group", []),
                is_trigger=bool(raw_node.get("is_trigger", False)),
                default_version=float(raw_node.get("default_version", 1.0)),
                supported_versions=supported_versions,
                inputs=raw_node.get("inputs", []),
                outputs=raw_node.get("outputs", []),
                credentials=credentials,
                properties=properties,
                operations=raw_node.get("operations", []),
                resources=raw_node.get("resources", []),
                version_details=raw_node.get("version_details", {})
            )

            # Store in indexes using case-insensitive lowercase keys
            self._nodes_by_canonical[node_def.canonical_name.lower()] = node_def
            self._nodes_by_short_name[node_def.name.lower()] = node_def

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NodeRegistry":
        """Factory constructor for testing or custom catalog data."""
        return cls(catalog_data=data)

    @property
    def provenance(self) -> Dict[str, Any]:
        """Metadata describing catalog source, n8n version, and extraction time."""
        return self._provenance

    def __len__(self) -> int:
        return len(self._nodes_by_canonical)

    def is_node_supported(self, node_type: str) -> bool:
        """Returns True if the node type is indexed in this registry."""
        key = node_type.strip().lower()
        return key in self._nodes_by_canonical or key in self._nodes_by_short_name

    def get_node(self, node_type: str) -> Optional[NodeDefinition]:
        """Resolves node definition by canonical type (e.g. 'n8n-nodes-base.if') or short name."""
        key = node_type.strip().lower()
        if key in self._nodes_by_canonical:
            return self._nodes_by_canonical[key]
        if key in self._nodes_by_short_name:
            return self._nodes_by_short_name[key]
        return None

    def is_version_supported(self, node_type: str, version: float) -> bool:
        """Checks if a specific typeVersion is supported by the node definition."""
        node = self.get_node(node_type)
        if not node:
            return False
        return any(abs(v - version) < 1e-4 for v in node.supported_versions)

    def is_operation_supported(self, node_type: str, operation: str, version: Optional[float] = None) -> bool:
        """Checks if a specific operation is supported by the node."""
        node = self.get_node(node_type)
        if not node:
            return False
        ops = node.get_operations(version=version)
        if not ops:
            # If node has no operation enum defined, any operation is considered open
            return True
        return operation in ops or operation.lower() in [o.lower() for o in ops]

    def get_required_parameters(self, node_type: str, version: Optional[float] = None) -> List[NodeParameterDefinition]:
        """Returns unconditionally required parameters for the specified node."""
        node = self.get_node(node_type)
        if not node:
            return []
        props = node.get_properties(version=version)
        return [p for p in props if p.required]

    def get_parameter(self, node_type: str, param_name: str, version: Optional[float] = None) -> Optional[NodeParameterDefinition]:
        """Retrieves definition of a specific parameter."""
        node = self.get_node(node_type)
        if not node:
            return None
        return node.get_parameter(param_name, version=version)

    def search(
        self,
        query: str = "",
        category: Optional[str] = None,
        is_trigger: Optional[bool] = None,
        operation: Optional[str] = None,
        limit: int = 50
    ) -> List[NodeDefinition]:
        """Searches available nodes with optional filters for category, trigger status, and operations.

        Args:
            query: Free-text search matching name, display name, or description.
            category: Filter by group category (e.g. 'transform', 'trigger').
            is_trigger: If specified, filter trigger nodes (True) or action nodes (False).
            operation: Filter nodes supporting a specific operation (e.g. 'getAll').
            limit: Maximum results to return.
        """
        scored_results: List[Tuple[int, NodeDefinition]] = []
        q = query.strip().lower()
        cat = category.strip().lower() if category else None
        op = operation.strip().lower() if operation else None

        cache_key = f"{q}|{cat}|{is_trigger}|{op}|{limit}"
        if cache_key in self._SEARCH_CACHE:
            return list(self._SEARCH_CACHE[cache_key])

        for node in self._nodes_by_canonical.values():
            if is_trigger is not None and node.is_trigger != is_trigger:
                continue

            if cat:
                groups_lower = [g.lower() for g in node.group]
                if cat not in groups_lower:
                    continue

            if op:
                ops_lower = [o.lower() for o in node.operations]
                if op not in ops_lower:
                    continue

            score = 0
            if q:
                node_name_lower = node.name.lower()
                canonical_lower = node.canonical_name.lower()
                display_lower = node.display_name.lower()
                desc_lower = node.description.lower()
                ops_lower = [o.lower() for o in node.operations]

                # 1. Full phrase matches
                if q == node_name_lower or q == canonical_lower:
                    score += 120
                elif q in node_name_lower:
                    score += 80
                elif q in canonical_lower:
                    score += 70
                elif q in display_lower:
                    score += 50
                elif any(q in o for o in ops_lower):
                    score += 30
                elif q in desc_lower:
                    score += 20

                # 2. Tokenized keyword matching
                tokens = [w for w in re.findall(r"[a-zA-Z0-9]+", q) if len(w) > 1 and w not in STOP_WORDS]
                for t in tokens:
                    if t == node_name_lower or t == canonical_lower:
                        score += 60
                    elif t in node_name_lower:
                        score += 35
                    elif t in canonical_lower:
                        score += 30
                    elif t in display_lower:
                        score += 25
                    elif any(t in o for o in ops_lower):
                        score += 15
                    elif t in desc_lower:
                        score += 10

                # 3. Domain synonyms and semantic associations
                if any(w in tokens for w in ["email", "mail", "inbox"]):
                    if any(k in node_name_lower for k in ["gmail", "imap", "email", "mail"]):
                        score += 40
                if "telegram" in tokens and "telegram" in node_name_lower:
                    score += 50
                if any(w in tokens for w in ["notification", "notify", "alert"]):
                    if any(k in node_name_lower for k in ["telegram", "slack", "discord", "email"]):
                        score += 25

                # 4. Trigger vs Action intent alignment
                if any(w in tokens for w in ["when", "receive", "incoming", "new", "trigger", "schedule", "webhook", "poll"]):
                    if node.is_trigger:
                        score += 30
                if any(w in tokens for w in ["send", "post", "create", "write", "notify", "action"]):
                    if not node.is_trigger:
                        score += 20

                if score <= 0:
                    continue
            else:
                score = 1

            scored_results.append((score, node))

        # Sort by score descending, then canonical name ascending
        scored_results.sort(key=lambda item: (-item[0], item[1].canonical_name))
        results = [node for _, node in scored_results[:limit]]

        if len(self._SEARCH_CACHE) >= self._CACHE_MAX_SIZE:
            try:
                first_k = next(iter(self._SEARCH_CACHE))
                self._SEARCH_CACHE.pop(first_k, None)
            except Exception:
                self._SEARCH_CACHE.clear()
        self._SEARCH_CACHE[cache_key] = results
        return results

    def list_nodes(self) -> List[NodeDefinition]:
        """Returns all registered node definitions."""
        return list(self._nodes_by_canonical.values())
