"""WebSocket endpoint — handles extension connections and log streaming."""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select, desc

from app.database import async_session
from app.models import Account, Log
from app.ws.manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()

_log_subscribers: dict[str, list[WebSocket]] = {}


async def _add_log(account_id: str, message: str, level: str = "info"):
    """Persist a log and push to any subscribed dashboards."""
    async with async_session() as session:
        log = Log(account_id=account_id, message=message, level=level)
        session.add(log)
        await session.commit()

    subs = _log_subscribers.get(account_id, [])
    dead = []
    for ws in subs:
        try:
            await ws.send_json({
                "type": "log",
                "account_id": account_id,
                "message": message,
                "level": level,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            dead.append(ws)
    for ws in dead:
        subs.remove(ws)


@router.websocket("/ws/extension/{account_id}")
async def extension_ws(ws: WebSocket, account_id: str):
    """WebSocket endpoint for Chrome extension connections."""
    async with async_session() as session:
        result = await session.execute(
            select(Account).where(Account.id == account_id)
        )
        account = result.scalar_one_or_none()
        if not account:
            await ws.close(code=4001, reason="Unknown account")
            return

    await manager.connect(account_id, ws)
    await _add_log(account_id, "Extension connected")

    try:
        while True:
            data = await ws.receive_json()
            req_id = data.get("req_id")
            if req_id:
                manager.resolve(req_id, data)
            elif data.get("cmd") == "ping":
                await ws.send_json({"cmd": "pong"})
    except WebSocketDisconnect:
        manager.disconnect(account_id)
        await _add_log(account_id, "Extension disconnected", level="warning")
    except Exception as e:
        logger.exception(f"Extension WS error for {account_id}")
        manager.disconnect(account_id)
        await _add_log(account_id, f"Extension error: {e}", level="error")


@router.websocket("/ws/logs/{account_id}")
async def logs_ws(ws: WebSocket, account_id: str):
    """WebSocket endpoint for dashboard live log streaming."""
    await ws.accept()
    if account_id not in _log_subscribers:
        _log_subscribers[account_id] = []
    _log_subscribers[account_id].append(ws)

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        _log_subscribers.get(account_id, []).remove(ws) if ws in _log_subscribers.get(account_id, []) else None


def get_log_fn(account_id: str):
    """Return a sync-compatible log function for use in the orchestrator."""
    def log_fn(message: str, level: str = "info"):
        asyncio.create_task(_add_log(account_id, message, level))
    return log_fn
