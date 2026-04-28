"""Unified LLM interface (OpenAI + Anthropic) with retry, validation, and dedup.

Every public ``generate_*`` returns a :class:`GenerationResult` so callers can
report exactly *why* a generation was dropped without relying on global state.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable

from app.content.prompts import (
    build_classification_prompt,
    build_degen_quote_comment_prompt,
    build_degen_reply_prompt,
    build_degen_tweet_prompt,
    build_position_extraction_prompt,
    build_quote_comment_prompt,
    build_reply_comment_prompt,
    build_thread_prompt,
    build_tweet_rephrase_prompt,
)
from app.content.validator import validate_and_fix

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


# --------------------------------------------------------------------------- #
#  Result type                                                                #
# --------------------------------------------------------------------------- #

@dataclass
class GenerationResult:
    """Outcome of a generation attempt.

    ``text`` is the validated, ready-to-post string when the call succeeded,
    ``None`` when every retry was rejected. ``reason`` describes the last
    rejection (empty on success).
    """
    text: str | None = None
    reason: str = ""

    def __bool__(self) -> bool:
        return self.text is not None


@dataclass
class ThreadResult:
    tweets: list[str] | None = None
    reason: str = ""

    def __bool__(self) -> bool:
        return self.tweets is not None


# --------------------------------------------------------------------------- #
#  LLM dispatch                                                               #
# --------------------------------------------------------------------------- #

def _active_api_key(cfg: dict) -> str:
    if cfg.get("llm_provider") == "anthropic":
        return cfg.get("anthropic_api_key", "")
    return cfg.get("openai_api_key", "")


def _active_model(cfg: dict) -> str:
    if cfg.get("llm_provider") == "anthropic":
        return cfg.get("anthropic_model", "claude-sonnet-4-20250514")
    return cfg.get("openai_model", "gpt-4o")


def _call_llm(cfg: dict, system: str, user: str, *,
              temperature: float = 0.9, max_tokens: int = 1024) -> str:
    if cfg.get("llm_provider") == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=cfg.get("anthropic_api_key", ""))
        response = client.messages.create(
            model=_active_model(cfg),
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text
    import openai
    client = openai.OpenAI(api_key=cfg.get("openai_api_key", ""))
    response = client.chat.completions.create(
        model=_active_model(cfg),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return response.choices[0].message.content


def _call_llm_with_image(cfg: dict, system: str, user: str, image_b64: str,
                         mime_type: str = "image/jpeg") -> str:
    if cfg.get("llm_provider") == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=cfg.get("anthropic_api_key", ""))
        response = client.messages.create(
            model=_active_model(cfg),
            max_tokens=256,
            system=system,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": image_b64}},
                    {"type": "text", "text": user},
                ],
            }],
        )
        return response.content[0].text
    import openai
    client = openai.OpenAI(api_key=cfg.get("openai_api_key", ""))
    response = client.chat.completions.create(
        model=_active_model(cfg),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}},
                {"type": "text", "text": user},
            ]},
        ],
        max_tokens=256,
    )
    return response.choices[0].message.content


def _call_llm_with_images(cfg: dict, system: str, user: str,
                          images: list[tuple[str, str]]) -> str:
    """Call the LLM with text + images. Falls back to plain call when no images."""
    if not images:
        return _call_llm(cfg, system, user)
    content: list[dict] = []
    for b64, mime in images:
        if cfg.get("llm_provider") == "anthropic":
            content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}})
        else:
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    content.append({"type": "text", "text": user})

    if cfg.get("llm_provider") == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=cfg.get("anthropic_api_key", ""))
        response = client.messages.create(
            model=_active_model(cfg),
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": content}],
        )
        return response.content[0].text
    import openai
    client = openai.OpenAI(api_key=cfg.get("openai_api_key", ""))
    response = client.chat.completions.create(
        model=_active_model(cfg),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ],
        max_tokens=1024,
        temperature=0.9,
    )
    return response.choices[0].message.content


# --------------------------------------------------------------------------- #
#  Retry / validation loop                                                    #
# --------------------------------------------------------------------------- #

def _user_with_feedback(user: str, last_reason: str, last_attempt: str) -> str:
    """On retry, tell the model what was wrong and not to repeat it."""
    if not last_reason:
        return user
    snippet = (last_attempt or "").strip().replace("\n", " ")
    if len(snippet) > 200:
        snippet = snippet[:200] + "..."
    feedback = (
        "\n\nIMPORTANT — your previous attempt was rejected.\n"
        f"Reason: {last_reason}\n"
    )
    if snippet:
        feedback += f"Rejected text: {snippet}\n"
    feedback += "Write a NEW post that fixes this issue. Do not repeat the same mistake."
    return user + feedback


def _passes_voice_judge(cfg: dict, text: str, voice: str) -> bool:
    """LLM-as-judge: does ``text`` plausibly match the configured persona?

    Fail-open everywhere except a clear NO so a single hiccup doesn't burn an
    entire generation.
    """
    voice = (voice or "").strip()
    text = (text or "").strip()
    if not voice or not text or not _active_api_key(cfg):
        return True
    system = (
        "You are a lenient voice/persona judge for short social posts. "
        "You will be given a TARGET VOICE (a description of the writer) and a CANDIDATE post. "
        "Default to YES. Only answer NO when the candidate is OBVIOUSLY incompatible with the persona — "
        "e.g. wrong gender markers, wildly wrong age register, persona-breaking phrases, or a tone that "
        "clearly contradicts the description. Short, neutral, on-topic posts should pass.\n\n"
        "Reply with EXACTLY one word: YES or NO. No explanation, no punctuation."
    )
    user = (
        f"TARGET VOICE:\n{voice}\n\n"
        f"CANDIDATE POST:\n{text}\n\n"
        "Is this OBVIOUSLY incompatible with the persona? Answer NO only if clearly incompatible, otherwise YES."
    )
    try:
        raw = _call_llm(cfg, system, user, temperature=0.0, max_tokens=4)
    except Exception as exc:
        logger.warning("[voice judge] failed, fail-open: %s", exc)
        return True
    answer = (raw or "").strip().upper()
    if answer.startswith("NO"):
        return False
    return True  # YES or anything ambiguous -> fail open


def _generate(
    cfg: dict, system: str, user: str, *,
    length_tier: str | None, dont_text: str, voice: str,
    call_fn: Callable[[str], str] | None = None,
    label: str = "generate",
) -> GenerationResult:
    """Canonical retry loop used by every text generator."""
    if call_fn is None:
        def call_fn(prompt: str) -> str:
            return _call_llm(cfg, system, prompt)
    use_voice_judge = bool(cfg.get("enable_voice_judge", False))

    last_reason = ""
    last_raw = ""
    for attempt in range(MAX_RETRIES):
        prompt = _user_with_feedback(user, last_reason, last_raw)
        try:
            raw = call_fn(prompt) or ""
        except Exception as exc:
            last_reason = f"LLM call failed: {exc}"
            logger.warning("[%s] attempt %d: %s", label, attempt + 1, last_reason)
            continue
        last_raw = raw
        result = validate_and_fix(raw, length_tier, dont_text=dont_text, voice=voice)
        if not result.passed:
            last_reason = result.reason or "validator rejected"
            logger.info("[%s] attempt %d rejected: %s | %.80s", label, attempt + 1, last_reason, raw)
            continue
        if use_voice_judge and voice and not _passes_voice_judge(cfg, result.text, voice):
            last_reason = "voice judge: text does not match the configured voice"
            logger.info("[%s] attempt %d rejected by voice judge | %.80s", label, attempt + 1, raw)
            continue
        return GenerationResult(text=result.text)
    logger.warning("[%s] all %d attempts rejected (last: %s)", label, MAX_RETRIES, last_reason)
    return GenerationResult(reason=last_reason or "no reason recorded")


# --------------------------------------------------------------------------- #
#  Public generators                                                          #
# --------------------------------------------------------------------------- #

def generate_tweet(cfg: dict, format_key: str, original_tweet: str,
                   length_tier: str = "MEDIUM",
                   recent_posts: list[str] | None = None,
                   enabled_topics: list[str] | None = None) -> GenerationResult:
    voice = cfg.get("voice_description", "")
    dont = cfg.get("dev_dont", "")
    system, user = build_tweet_rephrase_prompt(
        voice=voice,
        bad_examples=cfg.get("bad_examples", ""),
        good_examples=cfg.get("good_examples", ""),
        format_key=format_key,
        original_tweet=original_tweet,
        recent_posts=recent_posts,
        cfg=cfg,
        enabled_topics=enabled_topics,
        dev_do=cfg.get("dev_do", ""),
        dev_dont=dont,
    )
    return _generate(cfg, system, user,
                     length_tier=length_tier, dont_text=dont, voice=voice,
                     label="generate_tweet")


def generate_quote_comment(cfg: dict, original_tweet: str,
                           recent_posts: list[str] | None = None,
                           enabled_topics: list[str] | None = None,
                           image_b64_list: list[tuple[str, str]] | None = None,
                           ) -> GenerationResult:
    images = image_b64_list or []
    voice = cfg.get("voice_description", "")
    dont = cfg.get("dev_dont", "")
    system, user = build_quote_comment_prompt(
        voice=voice,
        bad_examples=cfg.get("bad_examples", ""),
        good_examples=cfg.get("good_examples", ""),
        original_tweet=original_tweet,
        recent_posts=recent_posts,
        cfg=cfg,
        enabled_topics=enabled_topics,
        has_images=bool(images),
        dev_do=cfg.get("dev_do", ""),
        dev_dont=dont,
    )
    call_fn = (lambda u: _call_llm_with_images(cfg, system, u, images)) if images else None
    return _generate(cfg, system, user,
                     length_tier="SHORT", dont_text=dont, voice=voice,
                     call_fn=call_fn, label="generate_quote")


def generate_reply_comment(cfg: dict, original_tweet: str, length_tier: str, tone: str,
                           recent_posts: list[str] | None = None,
                           post_type: str = "", reply_strategy: str = "",
                           existing_replies: list[str] | None = None,
                           positions: list[dict] | None = None,
                           enabled_topics: list[str] | None = None,
                           image_b64_list: list[tuple[str, str]] | None = None,
                           ) -> GenerationResult:
    images = image_b64_list or []
    voice = cfg.get("voice_description", "")
    dont = cfg.get("dev_dont", "")
    system, user = build_reply_comment_prompt(
        voice=voice,
        bad_examples=cfg.get("bad_examples", ""),
        good_examples=cfg.get("good_examples", ""),
        original_tweet=original_tweet,
        length_tier=length_tier, tone=tone,
        recent_posts=recent_posts,
        post_type=post_type, reply_strategy=reply_strategy,
        existing_replies=existing_replies, positions=positions,
        cfg=cfg,
        enabled_topics=enabled_topics,
        has_images=bool(images),
        dev_do=cfg.get("dev_do", ""),
        dev_dont=dont,
    )
    call_fn = (lambda u: _call_llm_with_images(cfg, system, u, images)) if images else None
    return _generate(cfg, system, user,
                     length_tier=length_tier, dont_text=dont, voice=voice,
                     call_fn=call_fn, label="generate_reply")


def generate_degen_tweet(cfg: dict, format_key: str, original_tweet: str,
                         recent_posts: list[str] | None = None) -> GenerationResult:
    voice = cfg.get("degen_voice_description", "")
    dont = cfg.get("degen_dont", "")
    system, user = build_degen_tweet_prompt(
        voice, format_key, original_tweet,
        cfg.get("degen_do", ""), dont,
        recent_posts=recent_posts,
    )
    return _generate(cfg, system, user,
                     length_tier="MEDIUM", dont_text=dont, voice=voice,
                     label="generate_degen_tweet")


def generate_degen_quote_comment(cfg: dict, original_tweet: str,
                                 recent_posts: list[str] | None = None) -> GenerationResult:
    voice = cfg.get("degen_voice_description", "")
    dont = cfg.get("degen_dont", "")
    system, user = build_degen_quote_comment_prompt(
        voice, original_tweet,
        cfg.get("degen_do", ""), dont,
        recent_posts=recent_posts,
    )
    return _generate(cfg, system, user,
                     length_tier="SHORT", dont_text=dont, voice=voice,
                     label="generate_degen_quote")


def generate_degen_reply_comment(cfg: dict, original_tweet: str, length_tier: str, tone: str,
                                 recent_posts: list[str] | None = None,
                                 post_type: str = "", reply_strategy: str = "",
                                 existing_replies: list[str] | None = None,
                                 positions: list[dict] | None = None) -> GenerationResult:
    voice = cfg.get("degen_voice_description", "")
    dont = cfg.get("degen_dont", "")
    system, user = build_degen_reply_prompt(
        voice, original_tweet, length_tier, tone,
        cfg.get("degen_do", ""), dont,
        recent_posts=recent_posts,
        post_type=post_type, reply_strategy=reply_strategy,
        existing_replies=existing_replies, positions=positions,
    )
    return _generate(cfg, system, user,
                     length_tier=length_tier, dont_text=dont, voice=voice,
                     label="generate_degen_reply")


def generate_thread(cfg: dict, thread_format_key: str, original_tweet: str,
                    recent_posts: list[str] | None = None,
                    enabled_topics: list[str] | None = None) -> ThreadResult:
    voice = cfg.get("voice_description", "")
    dont = cfg.get("dev_dont", "")
    system, user = build_thread_prompt(
        voice=voice,
        bad_examples=cfg.get("bad_examples", ""),
        good_examples=cfg.get("good_examples", ""),
        thread_format_key=thread_format_key,
        original_tweet=original_tweet,
        recent_posts=recent_posts,
        cfg=cfg,
        enabled_topics=enabled_topics,
        dev_do=cfg.get("dev_do", ""),
        dev_dont=dont,
    )
    use_voice_judge = bool(cfg.get("enable_voice_judge", False))
    last_reason = ""
    last_raw = ""
    for attempt in range(MAX_RETRIES):
        prompt = _user_with_feedback(user, last_reason, last_raw)
        try:
            raw = _call_llm(cfg, system, prompt) or ""
        except Exception as exc:
            last_reason = f"LLM call failed: {exc}"
            logger.warning("[generate_thread] attempt %d: %s", attempt + 1, last_reason)
            continue
        last_raw = raw
        tweets = [t.strip() for t in raw.split("---") if t.strip()]
        if len(tweets) < 2:
            last_reason = f"only {len(tweets)} thread segment(s), need >=2 separated by ---"
            logger.info("[generate_thread] attempt %d: %s", attempt + 1, last_reason)
            continue
        validated: list[str] = []
        rejected_reason = ""
        for tweet in tweets:
            r = validate_and_fix(tweet, "MEDIUM", dont_text=dont, voice=voice)
            if not r.passed:
                rejected_reason = r.reason
                break
            validated.append(r.text)
        if len(validated) < 2 or rejected_reason:
            last_reason = rejected_reason or "thread validation failed"
            logger.info("[generate_thread] attempt %d rejected: %s", attempt + 1, last_reason)
            continue
        if use_voice_judge and voice and not _passes_voice_judge(cfg, "\n\n".join(validated), voice):
            last_reason = "voice judge: thread does not match the configured voice"
            logger.info("[generate_thread] attempt %d rejected by voice judge", attempt + 1)
            continue
        return ThreadResult(tweets=validated)
    logger.warning("[generate_thread] all %d attempts rejected (last: %s)", MAX_RETRIES, last_reason)
    return ThreadResult(reason=last_reason or "no reason recorded")


# --------------------------------------------------------------------------- #
#  Classification + position extraction                                       #
# --------------------------------------------------------------------------- #

def _strip_code_fence(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def classify_post_with_llm(cfg: dict, post_text: str) -> dict | None:
    if not _active_api_key(cfg):
        return None
    system, user = build_classification_prompt(post_text)
    try:
        result = json.loads(_strip_code_fence(_call_llm(cfg, system, user)))
        if "type" in result and "reply_strategy" in result:
            return result
    except (json.JSONDecodeError, KeyError, IndexError, AttributeError):
        pass
    return None


_TOPIC_NORM_TRANS = str.maketrans({c: " " for c in "/-_&.,:;|"})


def _normalize_topic(s: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace.

    Lets the matcher accept LLM-emitted labels that drift in spacing or
    punctuation: 'AI / ML tools', 'AI/ML tools', 'ai-ml tools' all collapse to
    'ai ml tools'.
    """
    return " ".join(s.lower().translate(_TOPIC_NORM_TRANS).split())


def _match_enabled_topic_label(raw: object, enabled_topics: list[str]) -> str | None:
    """Map LLM output to an exact enabled topic label.

    Resolution order: exact -> case-insensitive -> normalized
    (whitespace/punctuation-insensitive) -> normalized substring.
    """
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s or s.lower() in ("null", "none", "n/a", "-", "omit", "skip"):
        return None
    if s in enabled_topics:
        return s
    s_lower = s.lower()
    for t in enabled_topics:
        if t.lower() == s_lower:
            return t
    s_norm = _normalize_topic(s)
    if not s_norm:
        return None
    norm_to_label = {_normalize_topic(t): t for t in enabled_topics}
    if s_norm in norm_to_label:
        return norm_to_label[s_norm]
    for n, t in norm_to_label.items():
        if n and (n in s_norm or s_norm in n):
            return t
    return None


def batch_classify_topics(cfg: dict, posts: list[dict],
                          enabled_topics: list[str]) -> dict[str, dict]:
    """One LLM call to classify every candidate post into at most one topic.

    Returns ``{post_url: {"topic": <enabled topic label>, "trading": bool}}``
    for posts that match an enabled topic. Politics, generic chatter, ads, and
    other off-topic posts are omitted (no key).
    """
    if not _active_api_key(cfg) or not posts or not enabled_topics:
        return {}

    topics_lines = "\n".join(f"- {t}" for t in enabled_topics)
    numbered: list[str] = []
    url_index: dict[int, str] = {}
    for i, p in enumerate(posts, 1):
        url_index[i] = p.get("url", "")
        numbered.append(f"{i}. {(p.get('text') or '')[:400]}")
    tweets_block = "\n".join(numbered)

    political_rule = ""
    if cfg.get("exclude_political_timeline", True):
        political_rule = (
            "\n- For domestic / foreign politics, elections, wars, geopolitics, or "
            "breaking news about governments — set \"topic\" to null. Be strict here.\n"
        )

    system = (
        "You categorize X/Twitter posts. For EACH numbered tweet, return a small JSON "
        "object describing what the tweet is about and whether it matches the user's "
        "enabled topics.\n\n"
        "For each tweet, output:\n"
        '  "topic": the BEST-FIT enabled topic from the list below, or null if the tweet '
        "is genuinely off-topic (politics, generic life chatter, ads, etc.).\n"
        '  "trading": true if the tweet is primarily about crypto / stock prices, '
        "charts, calls, or trading PnL; false otherwise.\n\n"
        "Be inclusive on \"topic\": if a tweet plausibly relates to one of the enabled "
        "categories — even tangentially — assign that category. Only use null when the "
        "tweet clearly belongs to none of them.\n\n"
        "Enabled topics (use these strings verbatim for \"topic\"):\n"
        f"{topics_lines}\n"
        f"{political_rule}\n"
        "Output rules:\n"
        "- Return ONLY a JSON object. Keys are tweet numbers as strings (\"1\", \"2\", ...).\n"
        "- Values are objects: {\"topic\": <string|null>, \"trading\": <bool>}.\n"
        "- Use the EXACT topic string from the list above; do not invent categories.\n"
        "- No markdown fences, no commentary.\n"
        'Example: {"1": {"topic": "AI / ML tools", "trading": false}, '
        '"2": {"topic": null, "trading": false}, '
        '"3": {"topic": "Crypto", "trading": true}}'
    )
    user = f"Categorize each tweet:\n\n{tweets_block}"
    max_out = min(4096, 384 + len(posts) * 110)

    try:
        mapping = json.loads(_strip_code_fence(
            _call_llm(cfg, system, user, temperature=0.15, max_tokens=max_out)
        ))
    except (json.JSONDecodeError, KeyError, ValueError, IndexError, AttributeError) as exc:
        logger.warning("[batch_classify_topics] LLM response parse failed: %s", exc)
        return {}

    out: dict[str, dict] = {}
    for idx_str, value in mapping.items():
        try:
            idx = int(idx_str)
        except (TypeError, ValueError):
            continue
        url = url_index.get(idx, "")
        if not url:
            continue
        # Tolerate both the new shape ({"topic": ..., "trading": ...}) and the
        # legacy shape (a bare topic string) so a partial model rollout can't
        # blow up classification.
        if isinstance(value, dict):
            topic_raw = value.get("topic")
            is_trading = bool(value.get("trading"))
        else:
            topic_raw = value
            is_trading = False
        topic = _match_enabled_topic_label(topic_raw, enabled_topics)
        if topic:
            out[url] = {"topic": topic, "trading": is_trading}
    return out


def extract_position(cfg: dict, posted_text: str) -> dict | None:
    if not _active_api_key(cfg):
        return None
    system, user = build_position_extraction_prompt(posted_text)
    try:
        result = json.loads(_strip_code_fence(_call_llm(cfg, system, user)))
        if result.get("topic") and result.get("stance"):
            return result
    except (json.JSONDecodeError, KeyError, IndexError, AttributeError):
        pass
    return None


def check_image_relevance_with_vision(cfg: dict, image_b64: str, generated_text: str,
                                      mime_type: str = "image/jpeg") -> bool:
    """True only when vision confirms relevance. Fail-closed on any error."""
    if not _active_api_key(cfg):
        return False
    system = "You verify whether an image is relevant to a tweet. Answer ONLY 'YES' or 'NO'."
    user = f'Does this image relate to the following tweet text? Answer YES or NO.\nTweet: "{generated_text}"'
    try:
        raw = _call_llm_with_image(cfg, system, user, image_b64, mime_type)
        return "YES" in (raw or "").upper()
    except Exception as exc:
        logger.warning("[vision] relevance check failed, skipping image: %s", exc)
        return False
