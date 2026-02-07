"""WebSocket manager for real-time per-project event broadcasting."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone

from starlette.websockets import WebSocket, WebSocketDisconnect


class OrchestratorWSManager:
    """Manages WebSocket connections grouped by project_id."""

    def __init__(self) -> None:
        self.connections: dict[str, list[WebSocket]] = defaultdict(list)

    async def connect(self, websocket: WebSocket, project_id: str) -> None:
        """Accept a WebSocket connection and subscribe to a project."""
        await websocket.accept()
        self.connections[project_id].append(websocket)

    async def disconnect(self, websocket: WebSocket, project_id: str) -> None:
        """Remove a WebSocket from a project's subscriber list."""
        conns = self.connections.get(project_id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns and project_id in self.connections:
            del self.connections[project_id]

    async def broadcast(self, project_id: str, event: str, data: dict | None = None) -> None:
        """Send a JSON message to all subscribers of a project."""
        message = {
            "event": event,
            "project_id": project_id,
            "data": data or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        payload = json.dumps(message)
        dead: list[WebSocket] = []
        for ws in self.connections.get(project_id, []):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws, project_id)

    async def handle_connection(self, websocket: WebSocket, project_id: str) -> None:
        """Receive loop — keeps the connection alive until client disconnects."""
        await self.connect(websocket, project_id)
        try:
            while True:
                # Wait for any message (keepalive pings, etc.)
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await self.disconnect(websocket, project_id)

    @property
    def active_connections(self) -> int:
        """Total number of active WebSocket connections across all projects."""
        return sum(len(conns) for conns in self.connections.values())
