"""Sequence scheduler — manages running orchestrators per account."""

import asyncio
import logging
from typing import Callable

from sqlalchemy import select
from app.database import async_session
from app.models import Account, Config, State
from app.engine.orchestrator import Orchestrator
from app.ws.manager import manager
from app.ws.handler import _add_log

logger = logging.getLogger(__name__)

_running: dict[str, Orchestrator] = {}


def _config_to_dict(cfg: Config) -> dict:
    """Convert a Config ORM object to a plain dict for the orchestrator."""
    return {c.name: getattr(cfg, c.name) for c in cfg.__table__.columns if c.name not in ("id", "account_id")}


def _state_to_dict(st: State) -> dict:
    """Convert a State ORM object to a plain dict."""
    return {c.name: getattr(st, c.name) for c in st.__table__.columns if c.name not in ("id", "account_id")}


async def _save_state(account_id: str, state_dict: dict):
    """Persist orchestrator state back to the database."""
    async with async_session() as session:
        result = await session.execute(
            select(State).where(State.account_id == account_id)
        )
        st = result.scalar_one_or_none()
        if st:
            for key, val in state_dict.items():
                if hasattr(st, key) and key not in ("id", "account_id"):
                    setattr(st, key, val)
            await session.commit()


async def start_sequence(account_id: str, count: int = 1) -> bool:
    """Start a farming batch for an account. Returns False if already running."""
    if account_id in _running:
        return False

    if not manager.is_connected(account_id):
        await _add_log(account_id, "Cannot start: no extension connected.", "error")
        return False

    async with async_session() as session:
        result = await session.execute(
            select(Config).where(Config.account_id == account_id)
        )
        cfg_obj = result.scalar_one_or_none()
        if not cfg_obj:
            await _add_log(account_id, "Cannot start: no config found.", "error")
            return False

        result = await session.execute(
            select(State).where(State.account_id == account_id)
        )
        st_obj = result.scalar_one_or_none()
        if not st_obj:
            st_obj = State(account_id=account_id)
            session.add(st_obj)
            await session.commit()

        cfg_dict = _config_to_dict(cfg_obj)
        state_dict = _state_to_dict(st_obj)

    async def log_fn(msg: str, level: str = "info"):
        await _add_log(account_id, msg, level)

    def sync_log(msg: str):
        asyncio.create_task(log_fn(msg))

    orch = Orchestrator(account_id, cfg_dict, state_dict, sync_log)
    _running[account_id] = orch

    async def run_and_cleanup():
        try:
            await orch.run_batch(count)
        except Exception as e:
            logger.exception(f"Orchestrator error for {account_id}")
            await log_fn(f"Fatal error: {e}", "error")
        finally:
            await _save_state(account_id, orch.state)
            _running.pop(account_id, None)
            await log_fn("Sequence batch finished.")

    asyncio.create_task(run_and_cleanup())
    await log_fn(f"Started {count}-sequence batch.")
    return True


async def stop_sequence(account_id: str) -> bool:
    """Cancel a running sequence for an account."""
    orch = _running.get(account_id)
    if not orch:
        return False
    orch.cancel()
    await _add_log(account_id, "Sequence cancelled by user.")
    return True


def is_running(account_id: str) -> bool:
    return account_id in _running
