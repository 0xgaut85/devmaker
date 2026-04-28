"""Smoke test for the rephrase/QRT execution fix.

Run as: ``python _integration_smoke.py``

Verifies the fix for "rephrased tweets and quote retweets don't fire when set
to 1 per sequence":

1. ``build_dev_action_plan`` puts rephrase/qrt/rt before bulk comments so they
   get first dibs on the eligible-post pool.
2. ``_select_source`` falls back to a relaxed handle filter so a handler still
   picks a post when earlier actions consumed the same creator.
3. End-to-end: with a 4-post pool and a (1 rephrase, 1 qrt, 1 rt, 4 comments,
   1 text, 2 follows) plan, the recorded action counts include >= 1 rephrase,
   >= 1 qrt, >= 1 rt and >= 1 comment.
4. ``filter_images_with_vision`` correctly unpacks ``(b64, mime)`` pairs so
   source media survives when ``use_vision_image_check`` is on.
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import patch

from app.content.generator import GenerationResult, ThreadResult
from app.content.prompts import (
    _FORMAT_STRUCTURE_WEIGHTS, _STRUCTURES, _structure_block,
    build_tweet_rephrase_prompt,
)
from app.content.rules import FORMAT_CATALOG, FORMAT_ORDER, LENGTH_FOR_FORMAT
from app.content.validator import (
    _opener_fingerprint, has_repeated_opener, validate_and_fix,
)
from app.engine import state as S
from app.engine.actions import (
    SequenceContext, _select_source, available_posts, filter_images_with_vision,
)
from app.engine.modes import _format_action_summary, run_dev_sequence
from app.engine.planner import build_dev_action_plan


PASS: list[str] = []
FAIL: list[tuple[str, str]] = []


def _say(name: str, ok: bool, detail: str = "") -> None:
    if ok:
        PASS.append(name)
        print(f"  PASS {name}")
    else:
        FAIL.append((name, detail))
        print(f"  FAIL {name}: {detail}")


# --------------------------------------------------------------------------- #
#  Test 1 - planner priority order                                            #
# --------------------------------------------------------------------------- #

def test_planner_priority_order():
    print("\n[1] planner priority order")
    cfg = {
        "seq_text_tweets": 1, "seq_rephrase_tweets": 1,
        "seq_qrts": 1, "seq_rts": 1, "seq_comments": 4,
        "seq_follows": 2, "seq_threads": 0,
    }
    actions = build_dev_action_plan(cfg)
    first_comment_idx = actions.index("comment")
    _say(
        "rephrase before first comment",
        actions.index("tweet_rephrase") < first_comment_idx,
        f"actions={actions}",
    )
    _say(
        "qrt before first comment",
        actions.index("qrt") < first_comment_idx,
        f"actions={actions}",
    )
    _say(
        "rt before first comment",
        actions.index("rt") < first_comment_idx,
        f"actions={actions}",
    )
    # threads should run absolute first when present
    cfg2 = {**cfg, "seq_threads": 1}
    actions2 = build_dev_action_plan(cfg2)
    _say(
        "thread runs absolute first",
        actions2[0] == "thread",
        f"actions={actions2}",
    )


# --------------------------------------------------------------------------- #
#  Test 2 - _select_source relaxed-handle path                                #
# --------------------------------------------------------------------------- #

def _make_ctx(pool_state: dict | None = None) -> SequenceContext:
    return SequenceContext(
        account_id="test",
        cfg={},
        state=pool_state or {},
        log=lambda _: None,
        ext=None,  # type: ignore[arg-type]
        human=None,  # type: ignore[arg-type]
        is_cancelled=lambda: False,
        persist=_async_noop,
        enabled_topics=["AI/ML tools"],
    )


async def _async_noop():  # pragma: no cover
    return None


def test_select_source_relaxes_handle_filter():
    print("\n[2] _select_source relaxed handle path")
    pool = [
        {"url": "https://x.com/a/1", "handle": "alice", "text": "post 1", "likes": 100, "_topic": "AI/ML tools"},
        {"url": "https://x.com/a/2", "handle": "alice", "text": "post 2", "likes": 90, "_topic": "AI/ML tools"},
    ]
    ctx = _make_ctx()
    ctx.used_urls = {"https://x.com/a/1"}
    ctx.used_handles = {"alice"}
    # Strict pass: every remaining post is by an already-used handle, so
    # available_posts(skip_handles=True) will (probabilistically) return [].
    # Force the deterministic case by patching random:
    with patch("app.engine.actions.random.random", return_value=1.0):
        # Strict path returns nothing because handle is excluded.
        strict = available_posts(pool, ctx, skip_handles=True)
        _say(
            "strict pass empty when handle is used",
            strict == [],
            f"strict={strict}",
        )
        chosen, reason = _select_source(ctx, pool)
    _say(
        "relaxed pass returns the remaining post",
        chosen is not None and chosen.get("url") == "https://x.com/a/2",
        f"chosen={chosen}, reason={reason}",
    )


def test_select_source_returns_none_when_pool_exhausted():
    pool = [{"url": "https://x.com/a/1", "handle": "alice", "text": "post 1", "likes": 50, "_topic": "AI/ML tools"}]
    ctx = _make_ctx()
    ctx.used_urls = {"https://x.com/a/1"}
    chosen, reason = _select_source(ctx, pool)
    _say(
        "exhausted pool returns (None, diagnostic)",
        chosen is None and "pool=1" in reason and "used_urls=1" in reason,
        f"chosen={chosen}, reason={reason}",
    )


# --------------------------------------------------------------------------- #
#  Test 3 - end-to-end run_dev_sequence with small pool                       #
# --------------------------------------------------------------------------- #

class _FakeExt:
    """Stub ExtensionClient that records every send and returns canned data."""

    def __init__(self, posts: list[dict]):
        self._posts = posts
        self.sent: list[tuple[str, dict]] = []

    async def send(self, cmd: str, **params) -> dict:
        self.sent.append((cmd, params))
        if cmd == "scrape_timeline":
            return {"status": "ok", "data": list(self._posts)}
        if cmd == "scrape_who_to_follow":
            return {"status": "ok", "data": ["new_handle_1", "new_handle_2"]}
        if cmd == "scrape_replies":
            return {"status": "ok", "data": []}
        if cmd in ("post_tweet", "post_comment", "quote_tweet",
                   "post_thread", "follow_user", "like_post",
                   "bookmark_post", "scroll", "lurk_scroll",
                   "session_warmup", "dismiss_compose"):
            return {"status": "ok"}
        if cmd == "retweet":
            return {"status": "ok"}
        return {"status": "ok"}

    async def safe_dismiss_compose(self) -> None:
        return None


class _FakeHuman:
    def __init__(self):
        self.cfg = {}
        self.state = {}
        self.log = lambda _: None

    async def organic_pause(self, short: bool = False) -> None: ...
    async def lurk_scroll(self, count=None) -> None: ...
    async def like_and_bookmark(self, post_url: str) -> None: ...
    async def session_warmup(self) -> None: ...
    async def wait_for_active_hours(self) -> None: ...
    async def cancellable_sleep(self, seconds: float) -> None: ...


def _stub_generators():
    """Patch the generator module's content functions to return varied text.

    Each call gets a unique sentence so the dedup + opener-fingerprint guards
    don't reject the second action onward (which would happen if every call
    returned identical text).
    """
    counter = {"n": 0}
    openers = [
        "Most database clusters", "Caching invalidation strategies",
        "Rust ownership models", "Cold-start latency optimizations",
        "Linear types should", "Distributed consensus protocols",
        "Shadow DOM updates", "Schema migrations rarely",
        "Graph traversal trade-offs", "Reactive frameworks ultimately",
        "Type erasure surprises", "Buffer pool sizing",
    ]

    def _next_text(*_a, **_kw):
        i = counter["n"]
        counter["n"] += 1
        opener = openers[i % len(openers)]
        return GenerationResult(
            text=f"{opener} matter more than people realize at production scale.",
            reason="",
        )

    def _next_thread(*_a, **_kw):
        return ThreadResult(tweets=["hook tweet here", "second tweet body"], reason="")

    return [
        patch("app.engine.actions.generate_tweet", side_effect=_next_text),
        patch("app.engine.actions.generate_quote_comment", side_effect=_next_text),
        patch("app.engine.actions.generate_reply_comment", side_effect=_next_text),
        patch("app.engine.actions.generate_thread", side_effect=_next_thread),
        patch("app.engine.actions.classify_post_with_llm", return_value=None),
        patch("app.engine.actions.extract_position", return_value=None),
        patch("app.engine.actions.fetch_images_as_base64", return_value=[]),
        # batch_classify_topics is imported lazily inside engagement_gate.
        # Patch at its source module so the lazy import sees the stub.
        patch(
            "app.content.generator.batch_classify_topics",
            return_value={
                f"https://x.com/u/{i}": {"topic": "AI/ML tools", "trading": False}
                for i in range(1, 5)
            },
        ),
    ]


def test_end_to_end_small_pool():
    print("\n[3] end-to-end run_dev_sequence with 4-post pool")

    posts = [
        {"url": f"https://x.com/u/{i}", "handle": f"user{i}",
         "text": f"thoughts on AI ML tools in production scenario {i}",
         "likes": 200 + i * 10, "image_urls": [], "_topic": "AI/ML tools"}
        for i in range(1, 5)
    ]

    cfg = {
        "openai_api_key": "sk-fake",
        "llm_provider": "openai",
        "topics": {"AI/ML tools": 5},
        "seq_text_tweets": 1, "seq_rephrase_tweets": 1,
        "seq_qrts": 1, "seq_rts": 1, "seq_comments": 4,
        "seq_follows": 2, "seq_threads": 0,
        "use_following_tab": False,
        "min_engagement_likes": 100,
        "use_llm_classification": True,
        "use_vision_image_check": False,
        "allow_trading_price_posts": False,
        "exclude_political_timeline": True,
        "active_hours_enabled": False,
        "action_delay_seconds": 0,
        "daily_max_tweets": 100, "daily_max_comments": 100,
        "daily_max_qrts": 100, "daily_max_rts": 100,
        "daily_max_follows": 100, "daily_max_likes": 100,
    }
    state: dict = {}

    ext = _FakeExt(posts)
    human = _FakeHuman()
    ctx = SequenceContext(
        account_id="acct",
        cfg=cfg,
        state=state,
        log=lambda msg: None,
        ext=ext,  # type: ignore[arg-type]
        human=human,  # type: ignore[arg-type]
        is_cancelled=lambda: False,
        persist=_async_noop,
        enabled_topics=["AI/ML tools"],
    )

    patches = _stub_generators()
    for p in patches:
        p.start()
    try:
        ok = asyncio.run(run_dev_sequence(ctx))
    finally:
        for p in patches:
            p.stop()

    counts = S.today_counts(state)
    _say("run_dev_sequence returned True", ok is True, f"ok={ok}")
    _say(
        "rephrase + text both fired (tweets >= 2)",
        counts.get("tweets", 0) >= 2,
        f"counts={dict(counts)}",
    )
    _say(
        "qrt fired (qrts >= 1)",
        counts.get("qrts", 0) >= 1,
        f"counts={dict(counts)}",
    )
    _say(
        "rt fired (rts >= 1)",
        counts.get("rts", 0) >= 1,
        f"counts={dict(counts)}",
    )
    _say(
        "at least one comment fired",
        counts.get("comments", 0) >= 1,
        f"counts={dict(counts)}",
    )

    # Verify the actual extension commands include both quote_tweet and at
    # least one post_tweet (the rephrase). This catches "the dispatcher ran
    # but the action silently bailed before sending".
    cmds_sent = [c for c, _ in ext.sent]
    _say(
        "extension received quote_tweet command",
        "quote_tweet" in cmds_sent,
        f"cmds={cmds_sent}",
    )
    _say(
        "extension received >=1 post_tweet (rephrase)",
        cmds_sent.count("post_tweet") >= 1,
        f"cmds={cmds_sent}",
    )
    _say(
        "extension received retweet command",
        "retweet" in cmds_sent,
        f"cmds={cmds_sent}",
    )


# --------------------------------------------------------------------------- #
#  Test 4 - filter_images_with_vision unpacking                               #
# --------------------------------------------------------------------------- #

def test_vision_unpack_correct():
    print("\n[4] filter_images_with_vision unpacking")
    ctx = _make_ctx()
    ctx.cfg = {"use_vision_image_check": True}
    image_urls = ["https://pbs.twimg.com/x.jpg", "https://pbs.twimg.com/y.png"]
    fake_b64_pairs = [("aGVsbG8=", "image/jpeg"), ("aGVsbG8=", "image/png")]
    captured_b64s: list[str] = []

    def _fake_check(cfg, b64, text):
        captured_b64s.append(b64)
        return True

    with patch("app.engine.actions.fetch_images_as_base64",
               return_value=fake_b64_pairs), \
         patch("app.engine.actions.check_image_relevance_with_vision",
               side_effect=_fake_check):
        kept = asyncio.run(filter_images_with_vision(ctx, image_urls, "any text"))

    _say(
        "vision check receives real b64 (not mime string)",
        all(b == "aGVsbG8=" for b in captured_b64s) and len(captured_b64s) == 2,
        f"captured={captured_b64s}",
    )
    _say(
        "all relevant images kept",
        kept == image_urls,
        f"kept={kept}",
    )


# --------------------------------------------------------------------------- #
#  Test 5 - opener fingerprint dedup                                          #
# --------------------------------------------------------------------------- #

def test_opener_fingerprint_basic():
    print("\n[5] opener fingerprint dedup")
    fp1 = _opener_fingerprint("Hot take: Postgres beats Mongo for OLTP.")
    fp2 = _opener_fingerprint("hot take: Rust beats Go for systems work.")
    fp3 = _opener_fingerprint("Postgres really shines on read-heavy workloads.")
    _say(
        "same opener -> same fingerprint",
        fp1 == fp2,
        f"fp1={fp1}, fp2={fp2}",
    )
    _say(
        "different opener -> different fingerprint",
        fp1 != fp3,
        f"fp1={fp1}, fp3={fp3}",
    )


def test_has_repeated_opener_catches_hot_take_repeat():
    recent = [
        "Hot take: Mongo is fine for prototypes.",
        "Hot take: Kubernetes is overkill for 99% of teams.",
    ]
    new_text = "Hot take: most ORMs hide bugs you'd catch in raw SQL."
    _say(
        "repeated 'Hot take:' opener flagged",
        has_repeated_opener(new_text, recent) is True,
    )
    fresh = "Most ORMs hide bugs you'd catch in raw SQL."
    _say(
        "fresh opener with same idea NOT flagged",
        has_repeated_opener(fresh, recent) is False,
    )


# --------------------------------------------------------------------------- #
#  Test 6 - tweet_media handler skips when no source has media                #
# --------------------------------------------------------------------------- #

def test_tweet_media_skips_when_no_source_media():
    print("\n[6] tweet_media skip path")
    from app.engine.actions import do_tweet_media
    pool = [
        {"url": "https://x.com/a/1", "handle": "alice", "text": "post 1",
         "likes": 100, "_topic": "AI/ML tools", "image_urls": []},
    ]
    logs: list[str] = []
    cfg = {
        "openai_api_key": "sk-fake", "llm_provider": "openai",
        "topics": {"AI/ML tools": 5},
        "daily_max_tweets": 100,
    }
    ctx = SequenceContext(
        account_id="t", cfg=cfg, state={},
        log=logs.append, ext=None, human=None,  # type: ignore[arg-type]
        is_cancelled=lambda: False, persist=_async_noop,
        enabled_topics=["AI/ML tools"], format_key="A",
    )
    ok = asyncio.run(do_tweet_media(ctx, pool))
    _say(
        "skips (returns False) when no source has media",
        ok is False,
        f"ok={ok}, logs={logs}",
    )
    _say(
        "skip log is explicit about why",
        any("no eligible source has media" in line for line in logs),
        f"logs={logs}",
    )


# --------------------------------------------------------------------------- #
#  Test 7 - end-of-sequence summary formatter                                 #
# --------------------------------------------------------------------------- #

def test_action_summary_format():
    print("\n[7] action summary formatter")
    s = _format_action_summary(
        requested={"qrt": 2, "tweet_rephrase": 1, "comment": 4},
        actual={"qrt": 0, "tweet_rephrase": 1, "comment": 3},
    )
    _say("flags qrt 0/2 as MISSED", "qrt 0/2" in s and "MISSED" in s, f"summary='{s}'")
    _say("rephrase 1/1 not flagged", "tweet_rephrase 1/1" in s and "tweet_rephrase 1/1  <--" not in s, f"summary='{s}'")
    _say("comment 3/4 flagged", "comment 3/4" in s and "MISSED" in s, f"summary='{s}'")


# --------------------------------------------------------------------------- #
#  Test 8 - structure picker variety + format anchoring                       #
# --------------------------------------------------------------------------- #

def test_structure_block_varies_for_flexible_format():
    print("\n[8] _structure_block variety for flexible format")
    # Format C is mid-flexibility — flowing/two_paragraphs/single_line/line_broken.
    # Over 200 calls we should see at least 3 distinct structures.
    seen: set[str] = set()
    for _ in range(200):
        block = _structure_block(format_key="C")
        for name, txt in _STRUCTURES.items():
            if block == txt:
                seen.add(name)
                break
    _say(
        "format C produces 3+ distinct structures across 200 picks",
        len(seen) >= 3,
        f"seen={seen}",
    )


def test_structure_block_pins_one_liner_format():
    # Format H (one-liner mic drop) MUST always pick single_line.
    seen: set[str] = set()
    for _ in range(50):
        block = _structure_block(format_key="H")
        for name, txt in _STRUCTURES.items():
            if block == txt:
                seen.add(name)
                break
    _say(
        "format H always pins to single_line",
        seen == {"single_line"},
        f"seen={seen}",
    )


def test_structure_block_falls_back_to_length():
    # No format key, just length tier. SHORT should bias to single/flowing.
    seen: set[str] = set()
    for _ in range(100):
        block = _structure_block(length_tier="SHORT")
        for name, txt in _STRUCTURES.items():
            if block == txt:
                seen.add(name)
                break
    _say(
        "length=SHORT only picks single_line / flowing_paragraph",
        seen.issubset({"single_line", "flowing_paragraph"}),
        f"seen={seen}",
    )


def test_structure_block_appears_in_prompt():
    # The rephrase prompt must contain the chosen STRUCTURE block so the LLM
    # actually sees the instruction.
    system, _user = build_tweet_rephrase_prompt(
        voice="casual dev",
        bad_examples="", good_examples="",
        format_key="C", original_tweet="postgres scales fine",
        recent_posts=[], cfg={},
        enabled_topics=["Database / backend"],
    )
    has_structure_word = "STRUCTURE:" in system
    _say(
        "rephrase prompt contains a STRUCTURE: block",
        has_structure_word,
        f"first 600 chars: {system[:600]!r}",
    )


# --------------------------------------------------------------------------- #
#  Test 9 - validator no longer auto-injects sentence-per-line                #
# --------------------------------------------------------------------------- #

def test_validator_does_not_break_flowing_paragraph():
    print("\n[9] validator preserves flowing paragraphs")
    flowing = (
        "Postgres handles read-heavy workloads better than people give it credit for, "
        "the planner is mature, and indexes do most of the heavy lifting. "
        "Most teams blame the database when the real bottleneck is their ORM."
    )
    res = validate_and_fix(flowing, length_tier="MEDIUM")
    _say(
        "MEDIUM flowing paragraph passes validation",
        res.passed,
        f"reason={res.reason}",
    )
    _say(
        "MEDIUM flowing paragraph is NOT mutated to sentence-per-line",
        "\n\n" not in res.text,
        f"text repr={res.text!r}",
    )


def test_validator_preserves_two_paragraph_structure():
    two_paras = (
        "Most ORMs hide bugs you would catch in raw SQL. "
        "Treat them as a convenience, not a contract.\n\n"
        "When latency matters, drop down to the query layer. "
        "Saves three round trips on the average request path."
    )
    res = validate_and_fix(two_paras, length_tier="LONG")
    _say(
        "two-paragraph LONG passes",
        res.passed,
        f"reason={res.reason}",
    )
    _say(
        "two-paragraph LONG keeps exactly one blank-line gap",
        res.text.count("\n\n") == 1,
        f"text repr={res.text!r}",
    )


# --------------------------------------------------------------------------- #
#  Test 10 - format catalog completeness                                      #
# --------------------------------------------------------------------------- #

def test_format_catalog_completeness():
    print("\n[10] format catalog completeness")
    _say(
        "FORMAT_CATALOG has at least 22 formats (was 12)",
        len(FORMAT_CATALOG) >= 22,
        f"count={len(FORMAT_CATALOG)}",
    )
    missing_length = [fk for fk in FORMAT_CATALOG if fk not in LENGTH_FOR_FORMAT]
    _say(
        "every format has a LENGTH_FOR_FORMAT entry",
        not missing_length,
        f"missing={missing_length}",
    )
    missing_weights = [fk for fk in FORMAT_CATALOG if fk not in _FORMAT_STRUCTURE_WEIGHTS]
    _say(
        "every format has a _FORMAT_STRUCTURE_WEIGHTS entry",
        not missing_weights,
        f"missing={missing_weights}",
    )
    # Every weight set must reference a known structure name.
    bad_weights: list[str] = []
    for fk, w in _FORMAT_STRUCTURE_WEIGHTS.items():
        for s_name in w.keys():
            if s_name not in _STRUCTURES:
                bad_weights.append(f"{fk}->{s_name}")
    _say(
        "every weight references a defined STRUCTURE",
        not bad_weights,
        f"bad={bad_weights}",
    )


# --------------------------------------------------------------------------- #
#  Test 11 - pick_diverse_format avoids recent + respects personality         #
# --------------------------------------------------------------------------- #

def test_pick_diverse_format_avoids_recent():
    print("\n[11] pick_diverse_format diversity")
    from app.engine.state import pick_diverse_format
    # Run 30 sequential picks; track how often the new pick is in the
    # last-5 window. Should be 0 (the picker excludes them entirely).
    state: dict = {"recent_formats": []}
    cfg: dict = {}
    repeats_in_window = 0
    last5_each_step: list[list[str]] = []
    for _ in range(30):
        recent_before = list(state.get("recent_formats", []))[-5:]
        last5_each_step.append(recent_before)
        pick = pick_diverse_format(cfg, state)
        if pick in recent_before:
            repeats_in_window += 1
    _say(
        "picker never repeats a format used in the last 5 picks",
        repeats_in_window == 0,
        f"repeats={repeats_in_window}",
    )
    distinct = len({p for window in last5_each_step for p in window})
    _say(
        "30 picks cover at least 12 distinct formats (true diversity)",
        distinct >= 12,
        f"distinct={distinct}",
    )


def test_pick_diverse_format_personality_bias():
    from app.engine.state import pick_diverse_format
    # High humor account should produce more wordplay (U) and one-liner
    # mic drop (H) than a default (humor=5) account.
    high_humor_cfg = {"personality_humor": 10, "personality_brevity": 5}
    default_cfg = {"personality_humor": 5, "personality_brevity": 5}
    n = 500

    high_state: dict = {"recent_formats": []}
    high_counts: dict[str, int] = {}
    for _ in range(n):
        p = pick_diverse_format(high_humor_cfg, high_state)
        high_counts[p] = high_counts.get(p, 0) + 1

    default_state: dict = {"recent_formats": []}
    default_counts: dict[str, int] = {}
    for _ in range(n):
        p = pick_diverse_format(default_cfg, default_state)
        default_counts[p] = default_counts.get(p, 0) + 1

    high_humor_picks = high_counts.get("U", 0) + high_counts.get("H", 0)
    default_humor_picks = default_counts.get("U", 0) + default_counts.get("H", 0)
    _say(
        "humor=10 produces strictly more U+H picks than humor=5",
        high_humor_picks > default_humor_picks,
        f"high U+H={high_humor_picks}, default U+H={default_humor_picks}",
    )


def test_pick_diverse_format_handles_old_state():
    # Old DB without recent_formats column: state["recent_formats"] is missing,
    # but state["last_format"] is set. Picker should still avoid that one.
    from app.engine.state import pick_diverse_format
    state = {"last_format": "C"}  # no recent_formats key at all
    cfg = {}
    # First pick should not be C (it should be excluded via last_format fallback)
    seen_c_first_pick = 0
    for _ in range(50):
        s = {"last_format": "C"}
        p = pick_diverse_format(cfg, s)
        if p == "C":
            seen_c_first_pick += 1
    _say(
        "old-state fallback excludes last_format from first pick",
        seen_c_first_pick == 0,
        f"saw C as first pick {seen_c_first_pick} times",
    )


# --------------------------------------------------------------------------- #
#  Test 12 - new structures resolve via _structure_block                      #
# --------------------------------------------------------------------------- #

def test_new_structures_can_be_picked():
    print("\n[12] new structures reachable")
    # Format G now uses lead_plus_bullets ~65% of the time.
    seen: set[str] = set()
    for _ in range(200):
        block = _structure_block(format_key="G")
        for name, txt in _STRUCTURES.items():
            if block == txt:
                seen.add(name)
                break
    _say(
        "format G can pick lead_plus_bullets",
        "lead_plus_bullets" in seen,
        f"seen={seen}",
    )
    # Format B now uses numbered_list majority of the time.
    seen_b: set[str] = set()
    for _ in range(200):
        block = _structure_block(format_key="B")
        for name, txt in _STRUCTURES.items():
            if block == txt:
                seen_b.add(name)
                break
    _say(
        "format B can pick numbered_list",
        "numbered_list" in seen_b,
        f"seen={seen_b}",
    )
    # Format Q (open question) pinned to single_line.
    seen_q: set[str] = set()
    for _ in range(50):
        block = _structure_block(format_key="Q")
        for name, txt in _STRUCTURES.items():
            if block == txt:
                seen_q.add(name)
                break
    _say(
        "format Q pinned to single_line",
        seen_q == {"single_line"},
        f"seen={seen_q}",
    )


# --------------------------------------------------------------------------- #
#  Runner                                                                     #
# --------------------------------------------------------------------------- #

def main() -> int:
    test_planner_priority_order()
    test_select_source_relaxes_handle_filter()
    test_select_source_returns_none_when_pool_exhausted()
    test_end_to_end_small_pool()
    test_vision_unpack_correct()
    test_opener_fingerprint_basic()
    test_has_repeated_opener_catches_hot_take_repeat()
    test_tweet_media_skips_when_no_source_media()
    test_action_summary_format()
    test_structure_block_varies_for_flexible_format()
    test_structure_block_pins_one_liner_format()
    test_structure_block_falls_back_to_length()
    test_structure_block_appears_in_prompt()
    test_validator_does_not_break_flowing_paragraph()
    test_validator_preserves_two_paragraph_structure()
    test_format_catalog_completeness()
    test_pick_diverse_format_avoids_recent()
    test_pick_diverse_format_personality_bias()
    test_pick_diverse_format_handles_old_state()
    test_new_structures_can_be_picked()

    print(f"\n{'='*60}")
    print(f"  passed: {len(PASS)}")
    print(f"  failed: {len(FAIL)}")
    if FAIL:
        for name, detail in FAIL:
            print(f"    - {name}: {detail}")
        return 1
    print("  ALL GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
