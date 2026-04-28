"""Top-level Orchestrator.

Owns the per-account batch lifecycle: warmup, dedup seeding, gating, and
dispatching to the right :mod:`app.engine.modes` runner. Action-level logic
lives in :mod:`app.engine.actions`; mode-level logic lives in
:mod:`app.engine.modes`. This file should stay short.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from app.engine import modes as M
from app.engine import state as S
from app.engine.actions import SequenceContext
from app.engine.ext import ExtensionClient
from app.engine.human import HumanSim


logger = logging.getLogger(__name__)

_VALID_MODES = ("dev", "degen", "rt_farm", "sniper")


class Orchestrator:
    """Runs farming batches by sending commands to the Chrome extension."""

    def __init__(self, account_id: str, cfg: dict, state: dict,
                 log_fn: Callable[[str], None]):
        self.account_id = account_id
        self.cfg = cfg
        self.state = state
        self.log = log_fn
        self._cancelled = False
        self._warmed_up = False
        self._seeded = False
        # The scheduler injects a state-flush coroutine so action handlers
        # can persist after every successful step.
        self.persist_state: Callable[[], Awaitable[None]] | None = None

    # -- Lifecycle --------------------------------------------------------

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    async def _persist_now(self) -> None:
        if self.persist_state is None:
            return
        try:
            await self.persist_state()
        except Exception:
            # Persistence failures must never break the running sequence, but
            # we DO want to know about them — silent swallow used to hide
            # transient DB outages until state went stale on restart.
            logger.warning("persist_state failed for %s", self.account_id, exc_info=True)
            self.log("[Persist] state flush failed (see server log) — continuing.")

    # -- Context --------------------------------------------------------

    def _build_context(self) -> SequenceContext:
        ext = ExtensionClient(self.account_id, self.log)
        human = HumanSim(ext, self.cfg, self.state, self.log, self.is_cancelled)
        ctx = SequenceContext(
            account_id=self.account_id,
            cfg=self.cfg,
            state=self.state,
            log=self.log,
            ext=ext,
            human=human,
            is_cancelled=self.is_cancelled,
            persist=self._persist_now,
            enabled_topics=S.enabled_topics(self.cfg),
        )
        return ctx

    # -- Dedup seeding ----------------------------------------------------

    async def _seed_dedup_from_own_profile(self, ctx: SequenceContext) -> None:
        handle = self.cfg.get("account_handle", "")
        if not handle:
            return
        try:
            resp = await ctx.ext.send("scrape_own_profile", handle=handle, max_posts=3)
        except Exception as e:
            self.log(f"[Dedup] Could not scrape own profile: {e}")
            return
        own_posts = resp.get("data") or []
        if not own_posts:
            return
        texts = self.state.setdefault("recent_posted_texts", [])
        for p in own_posts:
            t = (p.get("text") or "").strip()
            if t and t not in texts:
                texts.append(t)
        from app.engine.constants import RECENT_POSTED_TEXTS_CAP
        self.state["recent_posted_texts"] = texts[-RECENT_POSTED_TEXTS_CAP:]
        self.log(f"[Dedup] Seeded {len(own_posts)} recent own tweets for redundancy check.")

    # -- Sequence dispatch -----------------------------------------------

    async def run_sequence(self) -> bool:
        if self._cancelled:
            return False
        if S.all_caps_reached(self.state, self.cfg):
            self.log("[Cap] All daily limits reached. Stopping.")
            return False

        ctx = self._build_context()
        if not self._warmed_up:
            await ctx.human.session_warmup()
            self._warmed_up = True
            if self._cancelled:
                return False

        mode = self.cfg.get("farming_mode", "dev")
        if mode not in _VALID_MODES:
            self.log(f"ERROR: Unknown farming_mode={mode!r}; valid={_VALID_MODES}")
            return False
        try:
            if mode == "dev":
                return await M.run_dev_sequence(ctx)
            if mode == "degen":
                return await M.run_degen_sequence(ctx)
            if mode == "rt_farm":
                return await M.run_rt_farm_sequence(ctx)
            if mode == "sniper":
                return await M.run_sniper_sequence(ctx)
        except Exception as e:
            self.log(f"ERROR: {e}")
            await ctx.ext.safe_dismiss_compose()
            return False
        return False

    # -- Batch runner ----------------------------------------------------

    async def run_batch(self, count: int) -> None:
        self._warmed_up = False
        self._seeded = False

        for i in range(count):
            if self._cancelled:
                self.log("Batch cancelled.")
                return
            ctx = self._build_context()
            await ctx.human.wait_for_active_hours()
            if self._cancelled:
                return
            if S.all_caps_reached(self.state, self.cfg):
                self.log("[Cap] All caps reached. Stopping batch.")
                return

            # Seed dedup from our own profile once per batch.
            if not self._seeded:
                try:
                    await self._seed_dedup_from_own_profile(ctx)
                except Exception as e:
                    self.log(f"[Seed] dedup seed failed: {e}")
                self._seeded = True

            self.log(f"\n--- Sequence {i + 1}/{count} ---")
            success = await self.run_sequence()
            if not success:
                self.log(f"Sequence {i + 1} failed. Stopping.")
                return

            if i < count - 1:
                delay_min = int(self.cfg.get("sequence_delay_minutes", 45))
                self.log(f"Waiting {delay_min}min...")
                await ctx.human.cancellable_sleep(delay_min * 60)
        self.log("Batch complete.")
