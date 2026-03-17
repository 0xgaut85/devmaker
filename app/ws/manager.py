"""WebSocket connection manager — tracks connected extensions per account."""

import asyncio
import uuid
import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections from Chrome extensions.

    Each extension connects with an account_id. The backend sends commands
    and awaits responses keyed by a unique request_id.
    """

    def __init__(self):
        self._connections: dict[str, WebSocket] = {}
        self._pending: dict[str, asyncio.Future] = {}

    def is_connected(self, account_id: str) -> bool:
        return account_id in self._connections

    async def connect(self, account_id: str, ws: WebSocket):
        await ws.accept()
        old = self._connections.get(account_id)
        if old:
            try:
                await old.close(code=1000, reason="replaced")
            except Exception:
                pass
        self._connections[account_id] = ws
        logger.info(f"Extension connected for account {account_id}")

    def disconnect(self, account_id: str):
        self._connections.pop(account_id, None)
        for req_id, fut in list(self._pending.items()):
            if req_id.startswith(account_id + ":"):
                if not fut.done():
                    fut.set_exception(ConnectionError("Extension disconnected"))
                self._pending.pop(req_id, None)
        logger.info(f"Extension disconnected for account {account_id}")

    async def send_command(self, account_id: str, cmd: str, timeout: float = 60.0, **params) -> dict:
        """Send a command to the extension and wait for the response."""
        ws = self._connections.get(account_id)
        if not ws:
            raise ConnectionError(f"No extension connected for account {account_id}")

        req_id = f"{account_id}:{uuid.uuid4().hex[:8]}"
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[req_id] = future

        try:
            await ws.send_json({"req_id": req_id, "cmd": cmd, "params": params})
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Command {cmd} timed out after {timeout}s")
        finally:
            self._pending.pop(req_id, None)

    def resolve(self, req_id: str, response: dict):
        """Called when the extension sends a response back."""
        fut = self._pending.get(req_id)
        if fut and not fut.done():
            fut.set_result(response)

    async def broadcast_log(self, account_id: str, message: str, level: str = "info"):
        """Send a log message to any dashboard WebSocket listeners (not the extension)."""
        pass


manager = ConnectionManager()
