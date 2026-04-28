"""Human-like delays + soft engagement (lurk scroll, like, bookmark)."""

from __future__ import annotations

import asyncio
import random
from typing import Callable

from app.engine.constants import PAUSE_FLOOR_DEFAULT
from app.engine.ext import ExtensionClient
from app.engine import state as S


class HumanSim:
    """All the small "act like a human" calls. One per orchestrator."""

    def __init__(self, ext: ExtensionClient, cfg: dict, state: dict, log: Callable[[str], None],
                 is_cancelled: Callable[[], bool]):
        self.ext = ext
        self.cfg = cfg
        self.state = state
        self.log = log
        self._is_cancelled = is_cancelled

    async def cancellable_sleep(self, seconds: float) -> None:
        end = max(0.0, float(seconds))
        while end > 0 and not self._is_cancelled():
            slice_dur = 1.0 if end > 1.0 else end
            await asyncio.sleep(slice_dur)
            end -= slice_dur

    async def organic_pause(self, short: bool = False) -> None:
        """Pause between actions. Short variant used for inside-batch beats."""
        floor = max(1, int(self.cfg.get("action_delay_seconds", PAUSE_FLOOR_DEFAULT) or PAUSE_FLOOR_DEFAULT))
        if short:
            pause = random.uniform(max(1, floor // 2), floor * 2)
        else:
            pause = random.uniform(floor, floor * 4)
        self.log(f"  [Pause] {pause:.0f}s...")
        await self.cancellable_sleep(pause)
        if self._is_cancelled():
            return
        if random.random() < 0.3:
            try:
                await self.ext.send("scroll", count=1)
            except Exception:
                pass
            await self.cancellable_sleep(random.uniform(2, 5))

    async def session_warmup(self) -> None:
        self.log("[Warmup] Opening session naturally...")
        try:
            await self.ext.send("session_warmup", timeout=120)
        except Exception:
            pass
        self.log("[Warmup] Done.")

    async def lurk_scroll(self, count: int | None = None) -> None:
        count = count or random.randint(3, 8)
        self.log(f"  [Lurk] Scrolling past {count} posts...")
        try:
            await self.ext.send("lurk_scroll", count=count, timeout=120)
        except Exception:
            pass

    async def like_and_bookmark(self, post_url: str) -> None:
        if random.random() < 0.8 and S.can_act(self.state, self.cfg, "likes"):
            try:
                resp = await self.ext.send("like_post", post_url=post_url)
                status = resp.get("status")
                if status == "ok":
                    self.log("  [Like] Liked post.")
                    S.record_action(self.state, "likes")
                elif status == "already":
                    self.log("  [Like] Already liked.")
            except Exception:
                pass
            await asyncio.sleep(random.uniform(2, 6))
        if random.random() < 0.1:
            try:
                await self.ext.send("bookmark_post", post_url=post_url)
            except Exception:
                pass
            await asyncio.sleep(random.uniform(1, 3))

    async def wait_for_active_hours(self) -> None:
        if S.is_active_hours(self.cfg):
            return
        self.log("[Hours] Outside active hours. Waiting...")
        while not S.is_active_hours(self.cfg) and not self._is_cancelled():
            await self.cancellable_sleep(60)
