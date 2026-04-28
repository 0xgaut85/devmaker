"""Sequence-composition planner for the dev mode."""

from __future__ import annotations

import random


def build_dev_action_plan(cfg: dict) -> list[str]:
    """Return a shuffled list of action keys per the user's seq_* settings.

    Action keys correspond 1:1 with handlers in :mod:`app.engine.actions`.
    """
    actions: list[str] = []
    actions += ["tweet_text"]     * int(cfg.get("seq_text_tweets", 1) or 0)
    actions += ["tweet_rephrase"] * int(cfg.get("seq_rephrase_tweets", 1) or 0)
    actions += ["qrt"]            * int(cfg.get("seq_qrts", 1) or 0)
    actions += ["rt"]             * int(cfg.get("seq_rts", 1) or 0)
    actions += ["comment"]        * int(cfg.get("seq_comments", 4) or 0)
    actions += ["follow"]         * int(cfg.get("seq_follows", 2) or 0)
    actions += ["thread"]         * int(cfg.get("seq_threads", 0) or 0)
    random.shuffle(actions)
    return actions


# Action -> daily cap key (None = action handles its own cap or is uncapped).
ACTION_CAP_KEYS: dict[str, str | None] = {
    "tweet_text": "tweets",
    "tweet_rephrase": "tweets",
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
        f"{actions.count('comment')} comments, "
        f"{actions.count('qrt')} qrts, "
        f"{actions.count('rt')} rts, "
        f"{actions.count('follow')} follows, "
        f"{actions.count('thread')} threads."
    )
