"""Thin wrapper over the WebSocket connection manager with retry semantics.

Centralizes:
- per-command timeout (slow commands like post_* get a longer ceiling)
- one transparent reconnect attempt when the extension dies mid-sequence
- error->exception translation
"""

from __future__ import annotations

from typing import Callable

from app.engine.constants import (
    DEFAULT_CMD_TIMEOUT, RECONNECT_WAIT_SECONDS, SLOW_CMD_TIMEOUT, SLOW_COMMANDS,
)
from app.ws.manager import manager


class ExtensionClient:
    """Send commands to one specific account's connected extension."""

    def __init__(self, account_id: str, log: Callable[[str], None]):
        self.account_id = account_id
        self.log = log

    async def send(self, cmd: str, timeout: float | None = None, **params) -> dict:
        """Send a command and return the raw response dict.

        Auto-bumps timeout for known-slow commands. On a clean ConnectionError
        (extension dropped), waits up to RECONNECT_WAIT_SECONDS for the SW to
        reconnect, then retries once. Raises:
        - ``ConnectionError`` if the extension can't be reached.
        - ``TimeoutError`` if the extension does not respond in time.
        - ``RuntimeError`` if the extension responds with status="error".
        """
        if timeout is None:
            timeout = SLOW_CMD_TIMEOUT if cmd in SLOW_COMMANDS else DEFAULT_CMD_TIMEOUT

        try:
            result = await manager.send_command(self.account_id, cmd, timeout=timeout, **params)
        except ConnectionError:
            self.log(f"[Conn] Extension dropped — waiting {int(RECONNECT_WAIT_SECONDS)}s for reconnect...")
            ok = await manager.wait_until_connected(self.account_id, timeout=RECONNECT_WAIT_SECONDS)
            if not ok:
                raise
            self.log("[Conn] Extension reconnected — retrying command.")
            result = await manager.send_command(self.account_id, cmd, timeout=timeout, **params)

        if isinstance(result, dict) and result.get("status") == "error":
            raise RuntimeError(f"Extension error [{cmd}]: {result.get('error', 'unknown')}")
        return result

    async def safe_dismiss_compose(self) -> None:
        """Best-effort cleanup of any open compose dialog."""
        try:
            await self.send("dismiss_compose")
        except Exception:
            pass
