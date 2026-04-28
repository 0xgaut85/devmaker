"""Sequence-composition planner for the dev mode."""

from __future__ import annotations

import random


# Order tiers for action execution. Lower number = run first.
#
# Rare specialty actions (thread, rephrase, media-tweet, qrt) get first dibs
# on the eligible-post pool. Bulk comments come next, since they're typically
# the largest count and can absorb whatever's left. Original text tweets and
# follows don't consume the pool meaningfully so they go last.
#
# This is the fix for the "1 rephrase / 1 qrt per sequence and they never
# fire" problem: with a small eligible pool (e.g. 3-5 posts) and 4 comments
# in the plan, a uniform random shuffle would too often schedule rephrase /
# qrt AFTER the comments had drained every URL + handle.
#
# tweet_media is placed right after rephrase (same priority band) because it's
# strictly more constrained — it requires a source WITH images — so it should
# get its pick before the unconstrained variants do.
_PRIORITY: dict[str, int] = {
    "thread": 0,
    "tweet_media": 1,
    "tweet_rephrase": 2,
    "qrt": 3,
    "rt": 4,
    "comment": 5,
    "tweet_text": 6,
    "follow": 7,
}


def build_dev_action_plan(cfg: dict) -> list[str]:
    """Return an ordered list of action keys per the user's seq_* settings.

    Within each priority tier, order is randomized so consecutive sequences
    don't always run actions in identical order. Action keys correspond 1:1
    with handlers in :mod:`app.engine.actions`.
    """
    actions: list[str] = []
    actions += ["tweet_text"]     * int(cfg.get("seq_text_tweets", 1) or 0)
    actions += ["tweet_rephrase"] * int(cfg.get("seq_rephrase_tweets", 1) or 0)
    actions += ["tweet_media"]    * int(cfg.get("seq_media_tweets", 0) or 0)
    actions += ["qrt"]            * int(cfg.get("seq_qrts", 1) or 0)
    actions += ["rt"]             * int(cfg.get("seq_rts", 1) or 0)
    actions += ["comment"]        * int(cfg.get("seq_comments", 4) or 0)
    actions += ["follow"]         * int(cfg.get("seq_follows", 2) or 0)
    actions += ["thread"]         * int(cfg.get("seq_threads", 0) or 0)
    actions.sort(key=lambda a: (_PRIORITY.get(a, 99), random.random()))
    return actions


# Action -> daily cap key (None = action handles its own cap or is uncapped).
ACTION_CAP_KEYS: dict[str, str | None] = {
    "tweet_text": "tweets",
    "tweet_rephrase": "tweets",
    "tweet_media": "tweets",
    "qrt": "qrts",
    "rt": "rts",
    "thread": "tweets",
    "comment": "comments",  # also rechecked inside the action
    "follow": "follows",    # also rechecked inside the action
}


def summarize_plan(actions: list[str]) -> str:
    return (
        f"{len(actions)} actions: "
        f"{actions.count('tweet_text')} text, "
        f"{actions.count('tweet_rephrase')} rephrase, "
        f"{actions.count('tweet_media')} media, "
        f"{actions.count('comment')} comments, "
        f"{actions.count('qrt')} qrts, "
        f"{actions.count('rt')} rts, "
        f"{actions.count('follow')} follows, "
        f"{actions.count('thread')} threads."
    )
