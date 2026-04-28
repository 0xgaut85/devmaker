"""WebSocket endpoints — extension connection + dashboard log streaming."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.database import async_session
from app.models import Account, Log
from app.ws.manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()

# Server kills the connection if no message arrives in this many seconds. The
# extension pings every ~30s via chrome.alarms, so 90s gives us 3 missed pings
# before reaping (catches MV3 service-worker suspension promptly).
EXTENSION_IDLE_TIMEOUT = 90.0

_log_subscribers: dict[str, list[WebSocket]] = {}


async def _add_log(account_id: str, message: str, level: str = "info") -> None:
    """Persist a log row and push it to any subscribed dashboards."""
    async with async_session() as session:
        session.add(Log(account_id=account_id, message=message, level=level))
        await session.commit()

    subs = _log_subscribers.get(account_id, [])
    if not subs:
        return
    payload = {
        "type": "log",
        "account_id": account_id,
        "message": message,
        "level": level,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    dead: list[WebSocket] = []
    for ws in subs:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        try:
            subs.remove(ws)
        except ValueError:
            pass


@router.websocket("/ws/extension/{account_id}")
async def extension_ws(ws: WebSocket, account_id: str) -> None:
    """WebSocket endpoint for Chrome extension connections."""
    async with async_session() as session:
        account = (await session.execute(
            select(Account).where(Account.id == account_id)
        )).scalar_one_or_none()
        if not account:
            await ws.close(code=4001, reason="Unknown account")
            return

    await manager.connect(account_id, ws)
    await _add_log(account_id, "Extension connected")

    loop = asyncio.get_running_loop()
    last_recv = loop.time()

    async def watchdog() -> None:
        nonlocal last_recv
        while True:
            await asyncio.sleep(EXTENSION_IDLE_TIMEOUT)
            if loop.time() - last_recv > EXTENSION_IDLE_TIMEOUT:
                try:
                    await ws.close(code=1001, reason="idle timeout")
                except Exception:
                    pass
                return

    watchdog_task = asyncio.create_task(watchdog())

    try:
        while True:
            data = await ws.receive_json()
            last_recv = loop.time()
            req_id = data.get("req_id")
            if req_id:
                manager.resolve(req_id, data)
            elif data.get("cmd") == "ping":
                try:
                    await ws.send_json({"cmd": "pong"})
                except Exception:
                    break
    except WebSocketDisconnect:
        await _add_log(account_id, "Extension disconnected", level="warning")
    except Exception as e:
        logger.exception("Extension WS error for %s", account_id)
        await _add_log(account_id, f"Extension error: {e}", level="error")
    finally:
        watchdog_task.cancel()
        manager.disconnect(account_id)


@router.websocket("/ws/logs/{account_id}")
async def logs_ws(ws: WebSocket, account_id: str) -> None:
    """WebSocket endpoint for dashboard live log streaming."""
    await ws.accept()
    _log_subscribers.setdefault(account_id, []).append(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.debug("logs_ws receive failed", exc_info=True)
    finally:
        subs = _log_subscribers.get(account_id, [])
        if ws in subs:
            subs.remove(ws)
        if not subs:
            _log_subscribers.pop(account_id, None)


def get_log_fn(account_id: str):
    """Return a sync-compatible log function for use in the orchestrator."""
    def log_fn(message: str, level: str = "info") -> None:
        asyncio.create_task(_add_log(account_id, message, level))
    return log_fn
