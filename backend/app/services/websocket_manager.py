"""WebSocket Connection Hub and Lifecycle Event Broadcaster.

Manages active client WebSocket connections per conversation with secure user isolation,
thread-safe event broadcasting, snapshot caching for reconnect hydration, and dead socket cleanup.
"""
import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any, Dict, List, Optional, Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Singleton WebSocket connection and event hub."""

    _instance: Optional["WebSocketManager"] = None

    def __new__(cls) -> "WebSocketManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._connections = {}
            cls._instance._user_map = {}
            cls._instance._latest_events = {}
            cls._instance._lock = asyncio.Lock()
        return cls._instance

    def __init__(self) -> None:
        if not hasattr(self, "_initialized"):
            self._connections: Dict[str, Set[WebSocket]] = {}
            self._user_map: Dict[WebSocket, str] = {}
            self._latest_events: Dict[str, Dict[str, Any]] = {}
            self._initialized = True

    async def connect(self, conversation_id: str, user_id: str, websocket: WebSocket) -> None:
        """Registers an authenticated WebSocket connection for a conversation."""
        await websocket.accept()
        async with self._lock:
            if conversation_id not in self._connections:
                self._connections[conversation_id] = set()
            self._connections[conversation_id].add(websocket)
            self._user_map[websocket] = user_id

        # Deliver latest known event snapshot if available to immediately hydrate state
        latest = self._latest_events.get(conversation_id)
        if latest:
            try:
                await websocket.send_text(json.dumps(latest))
            except Exception as e:
                logger.debug("Failed to deliver initial event snapshot to WebSocket: %s", str(e))

    async def disconnect(self, conversation_id: str, websocket: WebSocket) -> None:
        """Unregisters a WebSocket connection safely."""
        async with self._lock:
            if conversation_id in self._connections:
                self._connections[conversation_id].discard(websocket)
                if not self._connections[conversation_id]:
                    self._connections.pop(conversation_id, None)
            self._user_map.pop(websocket, None)

    def is_connected(self, conversation_id: str) -> bool:
        """Returns True if there is at least one active connection for the conversation."""
        return bool(self._connections.get(conversation_id))

    async def broadcast(
        self,
        conversation_id: str,
        event_type: str,
        stage: str,
        status_code: str = "in_progress",
        message: Optional[str] = None,
        generation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timings: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """Broadcasts a genuine lifecycle event to authorized subscribers of the conversation."""
        event_payload = {
            "generation_id": generation_id or conversation_id,
            "conversation_id": conversation_id,
            "event_type": event_type,
            "stage": stage,
            "status": status_code,
            "message": message or "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
            "timings": timings or {},
        }

        # Cache latest event for quick snapshot recovery on client reconnect
        self._latest_events[conversation_id] = event_payload

        targets: List[WebSocket] = []
        async with self._lock:
            if conversation_id in self._connections:
                targets = list(self._connections[conversation_id])

        if targets:
            text_data = json.dumps(event_payload)
            dead_sockets = []
            for ws in targets:
                try:
                    await ws.send_text(text_data)
                except Exception as ws_err:
                    logger.debug("Dropping dead WebSocket for %s: %s", conversation_id, str(ws_err))
                    dead_sockets.append(ws)

            if dead_sockets:
                async with self._lock:
                    for ws in dead_sockets:
                        if conversation_id in self._connections:
                            self._connections[conversation_id].discard(ws)
                        self._user_map.pop(ws, None)

        return event_payload

    def get_latest_event(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """Returns the latest published event for the conversation."""
        return self._latest_events.get(conversation_id)

    def clear_conversation(self, conversation_id: str) -> None:
        """Cleans up event cache for completed or removed conversations."""
        self._latest_events.pop(conversation_id, None)


websocket_manager = WebSocketManager()


def get_websocket_manager() -> WebSocketManager:
    return websocket_manager
