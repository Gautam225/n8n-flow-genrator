"""Structured Workflow Intent Representation and Dynamic Node-Driven Intent Engine."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set
from pydantic import BaseModel, Field

from backend.app.models.conversation import ConversationMessage
from backend.app.orchestrator.schemas import (
    ClarificationOption,
    ClarificationQuestion,
)
from backend.app.services.node_registry import NodeRegistry

STOP_WORDS = {"and", "or", "the", "a", "an", "person", "persons", "row", "data"}



class NodeIntent(BaseModel):
    """Specification of an intended node in the planned workflow graph."""

    role: str = "action"  # "trigger", "action", "condition", "transform"
    service_name: str = ""  # Free-form requested service name, e.g. "Google Sheets", "Gmail", "Telegram"
    capability: str = ""  # Descriptive capability/event, e.g. "rowAdded", "sendMessage", "messageReceived"
    operation: Optional[str] = None
    node_type: Optional[str] = None  # Canonical n8n type if resolved in registry
    is_supported: bool = True  # Whether installed registry contains this node
    parameters: Dict[str, Any] = Field(default_factory=dict)
    credential_type: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def __init__(self, **data: Any):
        # Support legacy "service" keyword argument seamlessly
        if "service" in data and "service_name" not in data:
            data["service_name"] = data.pop("service")
        super().__init__(**data)

    @property
    def service(self) -> str:
        """Backward-compatible accessor returning lowercase service name or capability."""
        val = self.service_name or self.capability
        return val.lower() if val else ""


class WorkflowIntent(BaseModel):
    """Structured representation of extracted workflow requirements and data dependencies."""

    summary: str
    original_prompt: str = ""
    trigger: Optional[NodeIntent] = None
    actions: List[NodeIntent] = Field(default_factory=list)
    data_mappings: List[Dict[str, str]] = Field(default_factory=list)
    credential_requirements: List[str] = Field(default_factory=list)
    required_fields: List[str] = Field(default_factory=list)
    completed_answers: Dict[str, Any] = Field(default_factory=dict)
    outstanding_questions: List[str] = Field(default_factory=list)
    current_question: Optional[ClarificationQuestion] = None
    clarification_questions: List[ClarificationQuestion] = Field(default_factory=list)
    unresolved_requirements: List[str] = Field(default_factory=list)
    unsupported_services: List[str] = Field(default_factory=list)
    selected_provider: Optional[str] = None
    requested_action: Optional[str] = None

    @property
    def is_clarification_needed(self) -> bool:
        """True if critical unresolved requirements require asking the user."""
        return self.current_question is not None or len(self.clarification_questions) > 0

    @property
    def target_services(self) -> List[str]:
        """Returns list of identified services in the workflow intent."""
        svcs: List[str] = []
        if self.trigger and getattr(self.trigger, "service", None):
            svcs.append(self.trigger.service)
        for a in self.actions:
            svc = getattr(a, "service", None)
            if svc and svc not in svcs:
                svcs.append(svc)
        return svcs


VALID_TELEGRAM_DESTINATIONS = {"private_chat", "group", "channel"}

CANONICAL_SLOT_SYNONYMS: Dict[str, str] = {
    # Telegram
    "telegram_chat_id": "telegram_chat_id",
    "chat_id": "telegram_chat_id",
    "telegram_chat": "telegram_chat_id",
    "telegram_channel": "telegram_chat_id",
    "telegram_destination": "telegram_chat_id",
    "telegram_destination_type": "telegram_chat_id",
    "target_chat_id": "telegram_chat_id",
    "channel_id": "telegram_chat_id",
    "telegram_recipient": "telegram_chat_id",
    "recipient_id": "telegram_chat_id",

    # Google Sheets
    "google_sheets_document": "google_sheets_document",
    "spreadsheet_id": "google_sheets_document",
    "spreadsheet_url": "google_sheets_document",
    "sheet_id": "google_sheets_document",
    "document_id": "google_sheets_document",
    "google_sheet_id": "google_sheets_document",
    "google_sheets_url": "google_sheets_document",
    "google_sheet_url": "google_sheets_document",
    "sheet_url": "google_sheets_document",
    "google_spreadsheet_url": "google_sheets_document",
    "google_spreadsheet_id": "google_sheets_document",
    "spreadsheet_link": "google_sheets_document",
    "sheet_link": "google_sheets_document",
    "spreadsheetid": "google_sheets_document",
    "sheetid": "google_sheets_document",
    "spreadsheeturl": "google_sheets_document",
    "sheeturl": "google_sheets_document",
    "doc_id": "google_sheets_document",
    "doc": "google_sheets_document",
    "document": "google_sheets_document",
    "spreadsheet": "google_sheets_document",
    "sheet": "google_sheets_document",
    "google_sheet": "google_sheets_document",
    "google_spreadsheet": "google_sheets_document",

    # Sheet tab name
    "google_sheets_sheet_name": "google_sheets_sheet_name",
    "sheet_name": "google_sheets_sheet_name",
    "worksheet_name": "google_sheets_sheet_name",
    "tab_name": "google_sheets_sheet_name",
    "worksheet": "google_sheets_sheet_name",
    "tab": "google_sheets_sheet_name",
    "sheetname": "google_sheets_sheet_name",
    "worksheetname": "google_sheets_sheet_name",
    "tabname": "google_sheets_sheet_name",

    # Email provider
    "email_provider": "email_provider",
    "email_service": "email_provider",
    "email_type": "email_provider",
    "mail_provider": "email_provider",
    "provider": "email_provider",

    # Slack channel
    "slack_channel": "slack_channel",
    "channel": "slack_channel",
    "channel_name": "slack_channel",
    "slack_channel_name": "slack_channel",

    # Trigger
    "trigger": "trigger",
    "trigger_type": "trigger",
    "trigger_service": "trigger",
    "event_trigger": "trigger",
}


def canonicalize_slot_key(key: str) -> str:
    """Maps any slot key or synonym to its canonical slot identifier."""
    if not key:
        return ""
    norm = key.strip().lower().replace("-", "_").replace(" ", "_")
    return CANONICAL_SLOT_SYNONYMS.get(norm, norm)


def is_valid_telegram_chat_id(val: str) -> bool:
    """Validates Telegram destination. Bot usernames ending in 'bot' are strictly rejected."""
    if not val:
        return False
    clean = val.strip()
    # Accept recognized destination category preferences
    if clean.lower() in VALID_TELEGRAM_DESTINATIONS:
        return True
    # Reject bot usernames (e.g. Emcheckmebot, @Emcheckmebot, alert_bot)
    if re.search(r"bot$", clean, re.IGNORECASE):
        return False
    # Numeric chat ID (e.g. 123456789, or channel ID -100123456789, or group ID -987654321)
    if re.match(r"^-?\d{5,15}$", clean):
        return True
    # Public channel handle (@mychannel)
    if re.match(r"^@[a-zA-Z0-9_]{4,32}$", clean):
        return True
    return False


def extract_telegram_chat_id(text: str) -> Optional[str]:
    """Extracts Telegram Chat ID or public channel from natural language text."""
    if not text:
        return None
    # 1. Match explicit labeled chat ID (e.g. "my chat id is 8716438750", "chat id: -100123456789", "send to 8716438750")
    labeled_match = re.search(
        r"(?:chat\s*id|telegram\s*(?:chat|channel|id)|send\s+(?:alerts?|messages?|notifications?)\s+to)\s*(?:is|:|=)?\s*(-100\d{9,13}|-?\d{5,15}|@[a-zA-Z0-9_]{4,32})",
        text,
        re.IGNORECASE,
    )
    if labeled_match:
        cand = labeled_match.group(1).strip()
        if is_valid_telegram_chat_id(cand):
            return cand

    # 2. Match channel handle
    chan_match = re.search(r"@[a-zA-Z0-9_]{4,32}", text)
    if chan_match and is_valid_telegram_chat_id(chan_match.group(0)):
        return chan_match.group(0)

    # 3. Match numeric ID if telegram context exists
    if any(k in text.lower() for k in ("telegram", "chat", "notify", "message", "alert")):
        num_match = re.search(r"-100\d{9,13}|-?\b\d{6,14}\b", text)
        if num_match:
            cand = num_match.group(0).strip()
            if is_valid_telegram_chat_id(cand):
                return cand

    return None


def extract_spreadsheet_info(text: str) -> tuple[Optional[str], Optional[str]]:
    """Extracts Google Sheets document ID and worksheet/tab name from text or URL.

    Returns:
        tuple (document_id, tab_name_or_gid)
    """
    if not text:
        return None, None
    raw = text.strip()

    # 1. Match full Google Sheets URLs:
    # Handles:
    # https://docs.google.com/spreadsheets/d/1BxiMVs.../edit
    # https://docs.google.com/spreadsheets/u/0/d/1BxiMVs.../edit#gid=12345
    # https://docs.google.com/spreadsheets/d/1BxiMVs.../edit?gid=67890
    url_match = re.search(r"spreadsheets/(?:u/\d+/)?d/([a-zA-Z0-9-_]{20,})", raw)
    doc_id = url_match.group(1) if url_match else None

    # Check for gid or tab name parameter in URL
    tab_name = None
    if doc_id:
        gid_match = re.search(r"[?&#]gid=(\d+)", raw)
        if gid_match:
            tab_name = gid_match.group(1)
    else:
        # 2. Match standalone spreadsheet document ID
        # Google Spreadsheet IDs are typically base64-like strings ~44 chars long (at least 25 chars)
        id_match = re.match(r"^[a-zA-Z0-9-_]{25,60}$", raw)
        if id_match and not any(raw.lower().startswith(p) for p in ("http://", "https://", "ftp://")):
            doc_id = id_match.group(0)

    # 3. Check for tab/sheet name mentioned in text if not found in URL (e.g. "sheet named Leads", "tab: Active")
    if not tab_name:
        tab_match = re.search(
            r"(?:sheet|tab|worksheet)\s*(?:named|called|:|=)?\s*['\"]?([a-zA-Z0-9_\-\s]{1,50})['\"]?",
            raw,
            re.IGNORECASE,
        )
        if tab_match:
            cand = tab_match.group(1).strip()
            if cand.lower() not in ("url", "id", "link", "spreadsheet", "google sheets", "document"):
                tab_name = cand

    return doc_id, tab_name


# Semantic Trigger Aliases: Separated from core data model and extensible
# Semantic Trigger Aliases: Extensible mapping grounded in installed NodeRegistry
SEMANTIC_TRIGGER_ALIASES: Dict[str, Dict[str, Any]] = {
    "google_sheets": {
        "keywords": [
            "google sheets", "google sheet", "spreadsheet", "google sheets row",
            "new row in google sheets", "row added to google sheets", "row is added to google sheets",
            "new row added to google sheets", "new row added in google sheets"
        ],
        "node_type": "n8n-nodes-base.googleSheetsTrigger",
        "service_name": "Google Sheets",
        "capability": "rowAdded",
        "operation": "rowAdded",
        "parameters": {"event": "rowAdded"},
        "credential_type": "googleSheetsTriggerOAuth2Api",
    },
    "schedule": {
        "keywords": [
            "every morning", "every afternoon", "every evening", "every night",
            "every hour", "every day", "every minute", "every 5 minutes", "every week",
            "daily", "schedule", "cron", "interval", "hourly", "once a day", "at 9am", "at 8am"
        ],
        "node_type": "n8n-nodes-base.scheduleTrigger",
        "service_name": "Schedule",
        "capability": "interval",
        "operation": "interval",
        "parameters": {"rule": {"interval": [{"field": "hours", "hoursInterval": 1}]}},
    },
    "webhook": {
        "keywords": [
            "webhook", "http post", "api payload", "endpoint receives",
            "webhook receives", "when a webhook", "incoming webhook"
        ],
        "node_type": "n8n-nodes-base.webhook",
        "service_name": "Webhook",
        "capability": "default",
        "operation": "default",
        "parameters": {"path": "webhook", "httpMethod": "POST"},
    },
    "github": {
        "keywords": ["github", "github trigger", "pull request", "push to github", "github commit"],
        "node_type": "n8n-nodes-base.githubTrigger",
        "service_name": "GitHub",
        "capability": "event",
        "credential_type": "githubOAuth2Api",
    },
    "airtable": {
        "keywords": ["airtable", "airtable record", "airtable trigger"],
        "node_type": "n8n-nodes-base.airtableTrigger",
        "service_name": "Airtable",
        "capability": "recordAdded",
        "credential_type": "airtableTokenApi",
    },
    "stripe": {
        "keywords": ["stripe", "stripe payment", "stripe trigger"],
        "node_type": "n8n-nodes-base.stripeTrigger",
        "service_name": "Stripe",
        "capability": "event",
        "credential_type": "stripeApi",
    },
    "dropbox": {
        "keywords": ["dropbox", "dropbox file", "dropbox trigger"],
        "node_type": "n8n-nodes-base.dropboxTrigger",
        "service_name": "Dropbox",
        "capability": "fileCreated",
        "credential_type": "dropboxOAuth2Api",
    },
    "manual": {
        "keywords": ["manual trigger", "manual test", "trigger manually", "run manually"],
        "node_type": "n8n-nodes-base.manualTrigger",
        "service_name": "Manual",
        "capability": "manual",
        "operation": "manual",
        "parameters": {},
    },
}


def split_prompt_clauses(prompt: str) -> tuple[str, str]:
    """Splits an automation request into trigger and action clauses."""
    clean = prompt.strip()
    # "When/On/Whenever/If/Every X, send/notify/post/alert/forward Y"
    m = re.match(
        r"^(when\s+.+?|on\s+.+?|whenever\s+.+?|if\s+.+?|every\s+.+?)(?:,\s*(?:then\s*)?|\s+(?:then|and)\s+)(.+)$",
        clean,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # "Send/notify/post/alert Y when/on/whenever/every X"
    m2 = re.match(
        r"^(.+?)\s+(when\s+.+|whenever\s+.+|on\s+.+|every\s+.+)$",
        clean,
        re.IGNORECASE,
    )
    if m2:
        return m2.group(2).strip(), m2.group(1).strip()

    return clean, clean


class WorkflowIntentExtractor:
    """Extracts structured intent, resolves candidates dynamically against NodeRegistry, and manages batch clarification."""

    def __init__(self, node_registry: Optional[NodeRegistry] = None):
        self.node_registry = node_registry or NodeRegistry()

    def analyze(
        self,
        user_prompt: str,
        history: List[ConversationMessage],
        accumulated_slots: Dict[str, Any],
        original_prompt: Optional[str] = None,
    ) -> WorkflowIntent:
        """Analyzes user message and multi-turn conversation context into structured intent.

        Preserves original user intent across turns, accumulates answers dynamically,
        and presents all genuine missing requirements together in one batch.
        """
        # 1. Preserve original prompt throughout multi-turn conversation
        if not original_prompt:
            user_msgs = [m.content for m in history if m.role == "user" and m.content]
            original_prompt = user_msgs[0] if user_msgs else user_prompt

        raw_full_history = " ".join(
            [original_prompt] + [m.content for m in history if m.role == "user" and m.content] + [user_prompt]
        )
        full_history_text = raw_full_history.lower()
        current_text = user_prompt.strip()
        current_lower = current_text.lower()
        orig_lower = original_prompt.lower()

        # 1. Canonicalize accumulated slots from previous turns
        slots: Dict[str, Any] = {}
        for k, v in accumulated_slots.items():
            canon_k = canonicalize_slot_key(k)
            slots[canon_k] = v

        required_fields: List[str] = []
        completed_answers: Dict[str, Any] = {}
        outstanding_fields: List[str] = []
        unresolved: List[str] = []
        unsupported_services: List[str] = []

        # Collect all historical text sources from user and assistant turn summaries
        all_text_sources = [original_prompt]
        for m in history:
            if m.content:
                all_text_sources.append(m.content)
            if m.metadata_json and isinstance(m.metadata_json, dict):
                ans_list = m.metadata_json.get("clarification_answers") or []
                for a in ans_list:
                    if isinstance(a, dict) and a.get("custom_text"):
                        all_text_sources.append(a["custom_text"])
                    elif isinstance(a, dict) and a.get("selected_value"):
                        all_text_sources.append(a["selected_value"])
        all_text_sources.append(user_prompt)

        # 2. Extract / update slot answers from current text and history
        # Provider selection / mind-change handling (strictly when email trigger context exists)
        is_email_context = (
            "email" in full_history_text
            or "email_provider" in slots
            or any(w in full_history_text for w in ["gmail", "outlook", "imap"])
        )
        if is_email_context:
            for txt in reversed(all_text_sources):
                txt_l = txt.lower()
                if any(w in txt_l for w in ["gmail", "google workspace", "google mail"]):
                    slots["email_provider"] = "gmail"
                    break
                elif any(w in txt_l for w in ["outlook", "microsoft 365", "office365", "o365", "microsoft"]):
                    slots["email_provider"] = "outlook"
                    break
                elif any(w in txt_l for w in ["imap", "custom email", "self-hosted", "custom", "zoho", "fastmail", "yahoo", "proton"]):
                    slots["email_provider"] = "imap"
                    break

        # Sanitize previously accumulated telegram_chat_id if it's an invalid bot username
        if slots.get("telegram_chat_id") and not is_valid_telegram_chat_id(str(slots["telegram_chat_id"])):
            slots.pop("telegram_chat_id", None)

        # Telegram Chat ID extraction across current text and all historical sources
        if not slots.get("telegram_chat_id"):
            found_id = extract_telegram_chat_id(current_text)
            if not found_id:
                for txt in reversed(all_text_sources):
                    found_id = extract_telegram_chat_id(txt)
                    if found_id:
                        break
            if found_id:
                slots["telegram_chat_id"] = found_id

        # Google Sheets extraction across all text sources
        if not slots.get("google_sheets_document"):
            for txt in reversed(all_text_sources):
                doc_id, tab_val = extract_spreadsheet_info(txt)
                if doc_id:
                    slots["google_sheets_document"] = doc_id
                    completed_answers["google_sheets_document"] = doc_id
                    if tab_val and not slots.get("google_sheets_sheet_name"):
                        slots["google_sheets_sheet_name"] = tab_val
                        completed_answers["google_sheets_sheet_name"] = tab_val
                    break
        elif slots.get("google_sheets_document"):
            clean_doc = str(slots["google_sheets_document"]).strip()
            doc_id, tab_val = extract_spreadsheet_info(clean_doc)
            if doc_id:
                slots["google_sheets_document"] = doc_id
                completed_answers["google_sheets_document"] = doc_id
                if tab_val and not slots.get("google_sheets_sheet_name"):
                    slots["google_sheets_sheet_name"] = tab_val
                    completed_answers["google_sheets_sheet_name"] = tab_val

        # Worksheet / tab name in prompt (defaults to Sheet1 if omitted)
        if not slots.get("google_sheets_sheet_name"):
            for txt in reversed(all_text_sources):
                _, tab_val = extract_spreadsheet_info(txt)
                if tab_val:
                    slots["google_sheets_sheet_name"] = tab_val
                    completed_answers["google_sheets_sheet_name"] = tab_val
                    break
        slots.setdefault("google_sheets_sheet_name", "Sheet1")

        # Extract column names for spreadsheet-to-message mapping
        col_match = re.search(
            r"containing\s+(?:the\s+)?(?:person'?s?\s+)?([a-zA-Z0-9_,\s\band\b]+)",
            orig_lower,
            re.IGNORECASE,
        )
        if col_match and not slots.get("extracted_columns"):
            raw_cols = col_match.group(1)
            parsed_cols = [
                c.strip().strip("'\"")
                for c in re.split(r",|\band\b", raw_cols)
                if c.strip() and c.strip().lower() not in STOP_WORDS
            ]
            if parsed_cols:
                slots["extracted_columns"] = parsed_cols

        # Slack channel extraction across text sources
        if not slots.get("slack_channel"):
            for txt in reversed(all_text_sources):
                slack_chan_match = re.search(r"#([a-zA-Z0-9_-]{2,80})", txt)
                if slack_chan_match:
                    slots["slack_channel"] = f"#{slack_chan_match.group(1)}"
                    break

        # Split original prompt into trigger and action clauses to avoid misclassifying actions as triggers
        trig_clause, act_clause = split_prompt_clauses(original_prompt)
        trig_lower = trig_clause.lower()
        act_lower = act_clause.lower()

        trigger_intent: Optional[NodeIntent] = None
        action_intents: List[NodeIntent] = []
        data_mappings: List[Dict[str, str]] = []
        cred_requirements: List[str] = []
        selected_provider: Optional[str] = None

        # --- A. Dynamic Trigger Detection Grounded in Registry ---
        # 1. Check for specific supported trigger integrations first in trigger clause or prompt
        matched_trigger_alias: Optional[Dict[str, Any]] = None
        for alias_key, alias_spec in SEMANTIC_TRIGGER_ALIASES.items():
            if any(kw in trig_lower for kw in alias_spec["keywords"]) or any(kw in orig_lower for kw in alias_spec["keywords"]):
                matched_trigger_alias = alias_spec
                break

        # 2. Check for specific email providers in prompt
        is_gmail_explicit = any(w in trig_lower or w in orig_lower for w in ["gmail", "google workspace", "google mail"])
        is_outlook_explicit = any(w in trig_lower or w in orig_lower for w in ["outlook", "microsoft 365", "office365", "o365", "microsoft mail"])
        is_imap_explicit = any(w in trig_lower or w in orig_lower for w in ["imap", "custom email", "self-hosted email", "zoho", "fastmail"])

        # 3. Check for generic email trigger phrases ONLY in the trigger clause
        is_generic_email_trigger = (
            any(
                phrase in trig_lower
                for phrase in [
                    "receive an email", "when i receive an email", "when an email",
                    "incoming email", "new email", "get an email", "receive email",
                    "emails arrive", "email arrives", "when i get email", "email received",
                    "an email", "new mail", "incoming mail", "receive mail"
                ]
            )
            or trig_lower.strip() in ("email", "emails")
            or "email" in slots.get("trigger", "").lower()
            or "email_provider" in slots
        )

        if matched_trigger_alias and not is_generic_email_trigger:
            node_type = matched_trigger_alias.get("node_type")
            is_supp = self.node_registry.is_node_supported(node_type) if node_type else False
            cred = matched_trigger_alias.get("credential_type")
            if cred:
                cred_requirements.append(cred)

            trigger_params = dict(matched_trigger_alias.get("parameters", {}))

            if matched_trigger_alias.get("service_name") == "Google Sheets":
                # Check for Google Sheets document requirement
                doc_val = slots.get("google_sheets_document")
                if doc_val:
                    completed_answers["google_sheets_document"] = doc_val
                    trigger_params["documentId"] = {"mode": "list", "value": doc_val}
                else:
                    required_fields.append("google_sheets_document")
                    unresolved.append("google_sheets_document")
                    outstanding_fields.append("google_sheets_document")
                    trigger_params["documentId"] = {"mode": "list", "value": "={{ '<YOUR_SPREADSHEET_ID>' }}"}

                sheet_name_val = slots.get("google_sheets_sheet_name", "Sheet1")
                trigger_params["sheetName"] = {"mode": "list", "value": sheet_name_val}
                if "google_sheets_sheet_name" in slots:
                    completed_answers["google_sheets_sheet_name"] = sheet_name_val

            trigger_intent = NodeIntent(
                role="trigger",
                service_name=matched_trigger_alias["service_name"],
                capability=matched_trigger_alias.get("capability", "event"),
                operation=matched_trigger_alias.get("operation"),
                node_type=node_type,
                is_supported=is_supp,
                parameters=trigger_params,
                credential_type=cred,
            )

        elif is_gmail_explicit:
            slots["email_provider"] = "gmail"
            selected_provider = "gmail"
            completed_answers["email_provider"] = "gmail"
            trigger_intent = NodeIntent(
                role="trigger",
                service_name="Gmail",
                capability="messageReceived",
                operation="messageReceived",
                node_type="n8n-nodes-base.gmailTrigger",
                is_supported=self.node_registry.is_node_supported("n8n-nodes-base.gmailTrigger"),
                parameters={"event": "messageReceived", "simple": True},
                credential_type="gmailOAuth2",
            )
            cred_requirements.append("gmailOAuth2")

        elif is_outlook_explicit:
            slots["email_provider"] = "outlook"
            selected_provider = "outlook"
            completed_answers["email_provider"] = "outlook"
            trigger_intent = NodeIntent(
                role="trigger",
                service_name="Outlook",
                capability="messageReceived",
                operation="messageReceived",
                node_type="n8n-nodes-base.microsoftOutlookTrigger",
                is_supported=self.node_registry.is_node_supported("n8n-nodes-base.microsoftOutlookTrigger"),
                parameters={"event": "messageReceived"},
                credential_type="microsoftOutlookOAuth2Api",
            )
            cred_requirements.append("microsoftOutlookOAuth2Api")

        elif is_imap_explicit:
            slots["email_provider"] = "imap"
            selected_provider = "imap"
            completed_answers["email_provider"] = "imap"
            trigger_intent = NodeIntent(
                role="trigger",
                service_name="IMAP",
                capability="emailReceived",
                operation="emailReceived",
                node_type="n8n-nodes-base.emailReadImap",
                is_supported=self.node_registry.is_node_supported("n8n-nodes-base.emailReadImap"),
                parameters={"mailbox": "INBOX", "postProcessAction": "nothing", "format": "resolved"},
                credential_type="imap",
            )
            cred_requirements.append("imap")

        elif is_generic_email_trigger:
            required_fields.append("email_provider")
            email_provider = slots.get("email_provider")

            if email_provider:
                completed_answers["email_provider"] = email_provider
                selected_provider = email_provider
                if email_provider == "gmail":
                    trigger_intent = NodeIntent(
                        role="trigger",
                        service_name="Gmail",
                        capability="messageReceived",
                        operation="messageReceived",
                        node_type="n8n-nodes-base.gmailTrigger",
                        is_supported=self.node_registry.is_node_supported("n8n-nodes-base.gmailTrigger"),
                        parameters={"event": "messageReceived", "simple": True},
                        credential_type="gmailOAuth2",
                    )
                    cred_requirements.append("gmailOAuth2")
                elif email_provider == "outlook":
                    trigger_intent = NodeIntent(
                        role="trigger",
                        service_name="Outlook",
                        capability="messageReceived",
                        operation="messageReceived",
                        node_type="n8n-nodes-base.microsoftOutlookTrigger",
                        is_supported=self.node_registry.is_node_supported("n8n-nodes-base.microsoftOutlookTrigger"),
                        parameters={"event": "messageReceived"},
                        credential_type="microsoftOutlookOAuth2Api",
                    )
                    cred_requirements.append("microsoftOutlookOAuth2Api")
                else:
                    trigger_intent = NodeIntent(
                        role="trigger",
                        service_name="IMAP",
                        capability="emailReceived",
                        operation="emailReceived",
                        node_type="n8n-nodes-base.emailReadImap",
                        is_supported=self.node_registry.is_node_supported("n8n-nodes-base.emailReadImap"),
                        parameters={"mailbox": "INBOX", "postProcessAction": "nothing", "format": "resolved"},
                        credential_type="imap",
                    )
                    cred_requirements.append("imap")
            else:
                unresolved.append("email_provider")
                outstanding_fields.append("email_provider")
                trigger_intent = NodeIntent(
                    role="trigger",
                    service_name="Email",
                    capability="messageReceived",
                    node_type=None,
                    is_supported=True,
                    parameters={},
                )
        else:
            # Dynamic trigger search in NodeRegistry based on prompt keywords
            extracted_trigger_name = None
            prep_match = re.search(r"\bwhen\s+.*?\b(?:in|from|on|into|via)\s+([a-zA-Z0-9_]{3,35})\b", trig_clause, re.IGNORECASE)
            if prep_match:
                extracted_trigger_name = prep_match.group(1).strip()
            else:
                trig_match = re.search(r"\bwhen\s+(?:a\s+|an\s+)?([a-zA-Z0-9_\s]{2,30}?)(?:\s+(?:is|has|receives|triggers|occurs)|\b)", trig_clause, re.IGNORECASE)
                if trig_match:
                    extracted_trigger_name = trig_match.group(1).strip()

            candidate_nodes = []
            if extracted_trigger_name:
                candidate_nodes = self.node_registry.search(extracted_trigger_name, is_trigger=True, limit=3)

            if candidate_nodes:
                best_node = candidate_nodes[0]
                trigger_intent = NodeIntent(
                    role="trigger",
                    service_name=best_node.display_name,
                    capability="event",
                    node_type=best_node.canonical_name,
                    is_supported=True,
                )
            elif extracted_trigger_name and len(extracted_trigger_name.split()) <= 3 and extracted_trigger_name.lower() not in ("it", "user", "someone", "message", "event", "data"):
                # User requested a specific named trigger that is not in the installed catalog
                unsupported_services.append(extracted_trigger_name)
                trigger_intent = NodeIntent(
                    role="trigger",
                    service_name=extracted_trigger_name,
                    capability="event",
                    node_type=None,
                    is_supported=False,
                )
            else:
                if "manual" in orig_lower:
                    trigger_intent = NodeIntent(
                        role="trigger",
                        service_name="Manual",
                        capability="manual",
                        operation="manual",
                        node_type="n8n-nodes-base.manualTrigger",
                        is_supported=True,
                        parameters={},
                    )
                else:
                    required_fields.append("trigger_type")
                    unresolved.append("trigger_type")
                    outstanding_fields.append("trigger_type")

        # --- B. Dynamic Action Detection Grounded in Registry ---
        is_telegram_action = any(
            phrase in act_lower or phrase in orig_lower
            for phrase in ["telegram", "telegram bot", "telegram message", "notification on telegram", "notify on telegram", "notify telegram"]
        )

        is_slack_action = any(
            phrase in act_lower or phrase in orig_lower
            for phrase in ["slack", "slack channel", "notify slack", "post to slack"]
        )

        requested_action: Optional[str] = None
        if is_telegram_action:
            requested_action = "telegram"
            cred_requirements.append("telegramApi")
            required_fields.append("telegram_chat_id")

            chat_id = slots.get("telegram_chat_id") or slots.get("telegram_destination_type")
            if chat_id:
                completed_answers["telegram_chat_id"] = chat_id
            else:
                unresolved.append("telegram_chat_id")
                outstanding_fields.append("telegram_chat_id")

            actual_chat_id = slots.get("telegram_chat_id")
            if not actual_chat_id or actual_chat_id in VALID_TELEGRAM_DESTINATIONS:
                actual_chat_id = "={{ '<YOUR_TELEGRAM_CHAT_ID>' }}"

            telegram_params: Dict[str, Any] = {
                "resource": "message",
                "operation": "sendMessage",
                "chatId": actual_chat_id,
            }

            if is_generic_email_trigger or (trigger_intent and trigger_intent.service in ("gmail", "outlook", "imap", "email")):
                telegram_params["text"] = (
                    "={{ '📬 New Email Received\\n\\n' + "
                    "'From: ' + ($json.from || 'Unknown') + '\\n' + "
                    "'Subject: ' + ($json.subject || '(No Subject)') + '\\n\\n' + "
                    "($json.snippet || $json.text || '') }}"
                )
                data_mappings.append({"from": "email.from", "to": "telegram.text"})
                data_mappings.append({"from": "email.subject", "to": "telegram.text"})
            elif trigger_intent and "sheet" in trigger_intent.service_name.lower():
                extracted_cols = slots.get("extracted_columns")
                if extracted_cols:
                    for col in extracted_cols:
                        data_mappings.append({"from": f"sheets.{col}", "to": "telegram.text"})
                    lines = [
                        f"'{col.title()}: ' + ($json['{col}'] || $json['{col.title()}'] || $json['{col.lower()}'] || '')"
                        for col in extracted_cols
                    ]
                    telegram_params["text"] = "={{ '📊 New Row in Google Sheets\\n\\n' + " + " + '\\n' + ".join(lines) + " }}"
                else:
                    telegram_params["text"] = "={{ '📊 New Row in Google Sheets\\n\\n' + JSON.stringify($json) }}"
                    data_mappings.append({"from": "sheets.row", "to": "telegram.text"})
            else:
                telegram_params["text"] = "={{ 'Notification: ' + JSON.stringify($json) }}"

            action_intents.append(
                NodeIntent(
                    role="action",
                    service_name="Telegram",
                    capability="sendMessage",
                    operation="sendMessage",
                    node_type="n8n-nodes-base.telegram",
                    is_supported=self.node_registry.is_node_supported("n8n-nodes-base.telegram"),
                    parameters=telegram_params,
                    credential_type="telegramApi",
                )
            )

        if is_slack_action:
            requested_action = "slack"
            cred_requirements.append("slackApi")
            slack_channel = slots.get("slack_channel")
            if slack_channel:
                completed_answers["slack_channel"] = slack_channel
            else:
                required_fields.append("slack_channel")
                unresolved.append("slack_channel")
                outstanding_fields.append("slack_channel")

            action_intents.append(
                NodeIntent(
                    role="action",
                    service_name="Slack",
                    capability="post",
                    operation="post",
                    node_type="n8n-nodes-base.slack",
                    is_supported=self.node_registry.is_node_supported("n8n-nodes-base.slack"),
                    parameters={"channel": slots.get("slack_channel", "#general"), "text": "Notification"},
                    credential_type="slackApi",
                )
            )

        # Check for other dynamic actions requested in prompt
        if not action_intents:
            act_match = re.search(r"\b(?:send|post|create|notify|alert|update)\s+(?:a\s+|an\s+)?(?:message|notification|alert|record|ticket|event)?\s*(?:to|in|on)\s+([a-zA-Z0-9_\s]{2,30})", act_lower)
            if act_match:
                extracted_act_name = act_match.group(1).strip()
                if extracted_act_name not in ("telegram", "slack"):
                    cand_actions = self.node_registry.search(extracted_act_name, is_trigger=False, limit=3)
                    if cand_actions:
                        best_act = cand_actions[0]
                        action_intents.append(
                            NodeIntent(
                                role="action",
                                service_name=best_act.display_name,
                                capability="action",
                                node_type=best_act.canonical_name,
                                is_supported=True,
                            )
                        )
                    else:
                        unsupported_services.append(extracted_act_name.title())
                        action_intents.append(
                            NodeIntent(
                                role="action",
                                service_name=extracted_act_name.title(),
                                capability="action",
                                node_type=None,
                                is_supported=False,
                            )
                        )

        # 3. Dynamic Data-Driven Clarification Question Generation
        # Deduplicate: only generate questions for fields that are NOT already answered in slots!
        questions: List[ClarificationQuestion] = []
        seen_q_ids: Set[str] = set()

        def add_question(q: ClarificationQuestion) -> None:
            canon_key = canonicalize_slot_key(q.field_key)
            if canon_key in slots or canon_key in completed_answers:
                return
            q_key = q.id or q.field_key
            if q_key in seen_q_ids or q.field_key in seen_q_ids or canon_key in seen_q_ids:
                return
            seen_q_ids.add(q_key)
            seen_q_ids.add(q.field_key)
            seen_q_ids.add(canon_key)
            questions.append(q)

        # If user requested an unsupported service, generate an honest clarification explaining limitations
        for unsup in unsupported_services:
            unsup_key = f"unsupported_{unsup.lower()}"
            if unsup_key in slots:
                continue
            add_question(
                ClarificationQuestion(
                    id=unsup_key,
                    question=f"The requested service '{unsup}' is not available in the installed n8n node catalog. How would you like to handle this?",
                    field_key=unsup_key,
                    group="System: Node Support",
                    step_number=1,
                    input_type="single_select",
                    allow_other=True,
                    required=True,
                    is_required=True,
                    options=[
                        ClarificationOption(
                            label="Use Webhook Trigger",
                            value="webhook",
                            description=f"Send event payloads from {unsup} to a custom n8n Webhook URL",
                        ),
                        ClarificationOption(
                            label="Use HTTP Request Node",
                            value="http_request",
                            description=f"Connect to {unsup} via standard HTTP API requests",
                        ),
                        ClarificationOption(
                            label="Other",
                            value="other",
                            description="Specify a supported alternative service",
                        ),
                    ],
                    help_text=f"'{unsup}' is not an installed node in this n8n instance. You can integrate it using Webhook or HTTP Request.",
                )
            )

        for field in outstanding_fields:
            canon_f = canonicalize_slot_key(field)
            if canon_f in slots or canon_f in completed_answers:
                continue

            if field == "google_sheets_document":
                add_question(
                    ClarificationQuestion(
                        id="google_sheets_document",
                        question="What is your Google Spreadsheet URL or Spreadsheet ID?",
                        field_key="google_sheets_document",
                        group="Trigger: Google Sheets",
                        step_number=1,
                        input_type="url",
                        placeholder="https://docs.google.com/spreadsheets/d/... or spreadsheet ID",
                        examples=[
                            "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit"
                        ],
                        required=True,
                        is_required=True,
                        validation_rules={"format": "url_or_id"},
                        help_text="Provide the Google Sheets URL from your browser address bar or the alphanumeric spreadsheet ID. Google credentials will be configured in n8n.",
                    )
                )
                if "google_sheets_sheet_name" not in slots:
                    add_question(
                        ClarificationQuestion(
                            id="google_sheets_sheet_name",
                            question="Which worksheet / tab should be monitored?",
                            field_key="google_sheets_sheet_name",
                            group="Trigger: Google Sheets",
                            step_number=1,
                            input_type="text",
                            default_value="Sheet1",
                            placeholder="Sheet1",
                            required=False,
                            is_required=False,
                            help_text="The tab name at the bottom of your spreadsheet. Defaults to 'Sheet1' if omitted.",
                        )
                    )

            elif field == "email_provider":
                # Validate choices against registry: each choice must correspond to a verified node
                raw_options = [
                    ("Gmail", "gmail", "n8n-nodes-base.gmailTrigger", "Monitor incoming emails in your Google Gmail account via Gmail Trigger"),
                    ("Outlook", "outlook", "n8n-nodes-base.microsoftOutlookTrigger", "Monitor incoming emails in your Microsoft Outlook / 365 account"),
                    ("IMAP / Custom Email", "imap", "n8n-nodes-base.emailReadImap", "Connect to standard IMAP email server (Yahoo, custom, self-hosted)"),
                ]
                verified_options = []
                for label, val, node_t, desc in raw_options:
                    if self.node_registry.is_node_supported(node_t):
                        verified_options.append(ClarificationOption(label=label, value=val, description=desc))
                verified_options.append(ClarificationOption(label="Other", value="other", description="Enter your email service, for example Zoho Mail or a custom provider"))

                add_question(
                    ClarificationQuestion(
                        id="email_provider",
                        question="Which email service should trigger the workflow?",
                        field_key="email_provider",
                        group="Trigger: Email Service",
                        step_number=1,
                        input_type="single_select",
                        allow_other=True,
                        required=True,
                        is_required=True,
                        options=verified_options,
                        help_text="Select your email provider to configure the correct event trigger node.",
                    )
                )
            elif field == "telegram_chat_id":
                add_question(
                    ClarificationQuestion(
                        id="telegram_chat_id",
                        question="Where should the Telegram notification be sent?",
                        field_key="telegram_chat_id",
                        group="Action: Telegram Alert",
                        step_number=2,
                        input_type="single_select",
                        allow_other=True,
                        required=True,
                        is_required=True,
                        options=[
                            ClarificationOption(
                                label="A private chat",
                                value="private_chat",
                                description="Direct messages to your personal Telegram account",
                            ),
                            ClarificationOption(
                                label="A Telegram group",
                                value="group",
                                description="Notifications sent to a Telegram group",
                            ),
                            ClarificationOption(
                                label="A Telegram channel",
                                value="channel",
                                description="Broadcast notifications to a Telegram channel",
                            ),
                            ClarificationOption(
                                label="Other",
                                value="other",
                                description="Enter custom Chat ID or channel username",
                            ),
                        ],
                        help_text=(
                            "Enter your numeric Telegram Chat ID (e.g. 123456789) or public channel handle (e.g. @mychannel). "
                            "Bot usernames (e.g. @Emcheckmebot) cannot receive personal messages. Message @userinfobot to discover your Chat ID. "
                            "Your Bot Token must be configured directly in n8n (Credentials → Telegram API)."
                        ),
                        placeholder="e.g. 123456789 or @mychannel",
                        validation_rules={"format": "telegram_destination"},
                    )
                )
            elif field == "slack_channel":
                add_question(
                    ClarificationQuestion(
                        id="slack_channel",
                        question="Which Slack channel should receive notifications?",
                        field_key="slack_channel",
                        group="Action: Slack Notification",
                        step_number=2,
                        input_type="text",
                        placeholder="#general",
                        required=True,
                        is_required=True,
                        help_text="Provide the Slack channel name (e.g. #general, #alerts) or channel ID.",
                    )
                )
            elif field == "trigger_type":
                # Only ask if the trigger was completely generic and unspecified
                add_question(
                    ClarificationQuestion(
                        id="trigger_type",
                        question="How should this automation be triggered?",
                        field_key="trigger",
                        group="Trigger: Automation Entrypoint",
                        step_number=1,
                        input_type="single_select",
                        allow_other=True,
                        required=True,
                        is_required=True,
                        options=[
                            ClarificationOption(label="When an Email Arrives", value="email", description="Trigger on incoming email"),
                            ClarificationOption(label="On a Schedule", value="schedule", description="Run at regular intervals"),
                            ClarificationOption(label="Via Webhook", value="webhook", description="Trigger via HTTP endpoint"),
                            ClarificationOption(label="Other", value="other", description="Custom event trigger"),
                        ],
                    )
                )

        for k, v in slots.items():
            if v is not None and v != "" and k not in completed_answers:
                completed_answers[k] = v

        current_question = questions[0] if questions else None

        summary = (
            f"Workflow intent: Trigger({trigger_intent.service_name if trigger_intent else 'unresolved'}) -> "
            f"Actions({', '.join([a.service_name for a in action_intents]) or 'none'})"
        )

        return WorkflowIntent(
            summary=summary,
            original_prompt=original_prompt,
            trigger=trigger_intent,
            actions=action_intents,
            data_mappings=data_mappings,
            credential_requirements=cred_requirements,
            required_fields=required_fields,
            completed_answers=completed_answers,
            outstanding_questions=[q.id for q in questions],
            current_question=current_question,
            clarification_questions=questions,
            unresolved_requirements=[q.field_key for q in questions],
            unsupported_services=unsupported_services,
            selected_provider=selected_provider,
            requested_action=requested_action,
        )

