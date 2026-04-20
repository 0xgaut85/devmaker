"""Unified LLM interface supporting OpenAI and Anthropic — adapted for web backend."""

import base64
import json
import logging
import random

logger = logging.getLogger(__name__)

from app.content.prompts import (
    build_tweet_rephrase_prompt,
    build_quote_comment_prompt,
    build_reply_comment_prompt,
    build_project_reply_prompt,
    build_degen_tweet_prompt,
    build_degen_quote_comment_prompt,
    build_degen_reply_prompt,
    build_thread_prompt,
    build_classification_prompt,
    build_position_extraction_prompt,
)
from app.content.rules import PROJECT_COMMENT_TEMPLATES, PROJECT_BANNED_WORDS
from app.content.validator import validate_and_fix, ValidationResult

MAX_RETRIES = 3

# Last rejection reason from any generator. The orchestrator reads this when a
# generate_* call returns None so the dashboard can show *why* every retry
# failed (Don't rule, voice judge, length cap, banned phrase, etc.).
_LAST_REJECTION: str = ""


def get_last_rejection_reason() -> str:
    return _LAST_REJECTION


def _record_rejection(reason: str) -> None:
    global _LAST_REJECTION
    _LAST_REJECTION = reason or ""


def _clear_rejection() -> None:
    global _LAST_REJECTION
    _LAST_REJECTION = ""


def _user_with_feedback(user: str, last_reason: str, last_attempt: str) -> str:
    """Append a corrective feedback block so the LLM self-corrects on retry.

    Without this, retries are pure dice rolls — same prompt, same temperature,
    same likely failure mode. The block is only added on retries (last_reason set).
    """
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


def _generate_with_retries(
    cfg: dict,
    system: str,
    user: str,
    *,
    length_tier: str | None,
    dont_text: str,
    voice: str,
    call_fn=None,
    label: str = "generate",
    use_voice_judge: bool | None = None,
) -> str | None:
    """Canonical retry loop used by every generator.

    - Calls `call_fn` (or `_call_llm`) up to MAX_RETRIES times.
    - On rejection, appends the validator's reason to the user prompt so the
      LLM can self-correct instead of rolling the dice again.
    - Voice judge is opt-in via cfg["enable_voice_judge"] (defaults to off
      because a second LLM call per attempt doubles cost and silently
      kills generation when the judge is overstrict).
    """
    if call_fn is None:
        call_fn = lambda u: _call_llm(cfg, system, u)
    if use_voice_judge is None:
        use_voice_judge = bool(cfg.get("enable_voice_judge", False))
    _clear_rejection()
    last_reason = ""
    last_raw = ""
    for attempt in range(MAX_RETRIES):
        prompt = _user_with_feedback(user, last_reason, last_raw)
        raw = call_fn(prompt)
        last_raw = raw or ""
        result = validate_and_fix(raw or "", length_tier, dont_text=dont_text, voice=voice)
        if not result.passed:
            last_reason = result.reason or "validator rejected"
            _record_rejection(last_reason)
            logger.info("[%s] attempt %d rejected: %s | %.80s", label, attempt + 1, last_reason, last_raw)
            continue
        if use_voice_judge and voice and not _passes_voice_judge(cfg, result.text, voice):
            last_reason = "voice judge: text does not match the configured voice"
            _record_rejection(last_reason)
            logger.info("[%s] attempt %d rejected by voice judge | %.80s", label, attempt + 1, last_raw)
            continue
        return result.text
    logger.warning("[%s] all %d attempts rejected (last: %s)", label, MAX_RETRIES, last_reason)
    return None


def _active_api_key(cfg: dict) -> str:
    if cfg.get("llm_provider") == "anthropic":
        return cfg.get("anthropic_api_key", "")
    return cfg.get("openai_api_key", "")


def _active_model(cfg: dict) -> str:
    if cfg.get("llm_provider") == "anthropic":
        return cfg.get("anthropic_model", "claude-sonnet-4-20250514")
    return cfg.get("openai_model", "gpt-4o")


def _call_llm(
    cfg: dict,
    system: str,
    user: str,
    *,
    temperature: float = 0.9,
    max_tokens: int = 1024,
) -> str:
    """Call the configured LLM provider and return raw text.
    cfg is a dict with llm_provider, openai_api_key, anthropic_api_key, etc."""
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
    else:
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


def _call_llm_with_image(cfg: dict, system: str, user: str, image_b64: str, mime_type: str = "image/jpeg") -> str:
    """Call the LLM with a base64-encoded image for vision tasks."""
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
    else:
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


def _call_llm_with_images_for_generation(
    cfg: dict, system: str, user: str,
    images: list[tuple[str, str]],
) -> str:
    """Call the LLM with text + images for full generation (1024 tokens)."""
    if not images:
        return _call_llm(cfg, system, user)
    content = []
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
    else:
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


def _passes_voice_judge(cfg: dict, text: str, voice: str) -> bool:
    """LLM-as-judge: does `text` plausibly sound like the configured voice?

    Returns True when:
    - voice is empty (nothing to judge against),
    - no API key is configured (fail-open so generation isn't blocked by missing creds),
    - or the judge LLM answers YES.

    Returns False on a clear NO. Any unexpected/ambiguous output -> fail-open True
    so a single judge hiccup doesn't waste an entire generation.
    """
    voice = (voice or "").strip()
    text = (text or "").strip()
    if not voice or not text:
        return True
    if not _active_api_key(cfg):
        return True
    system = (
        "You are a lenient voice/persona judge for short social posts. "
        "You will be given a TARGET VOICE (a description of the writer) and a CANDIDATE post. "
        "Default to YES. Only answer NO when the candidate is OBVIOUSLY incompatible with the persona — "
        "e.g. wrong gender markers, wildly wrong age register, persona-breaking phrases, or a tone that "
        "clearly contradicts the description. Short, neutral, on-topic posts should pass. "
        "Do not require slang, emojis, or stereotyped speech.\n\n"
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
    if answer.startswith("YES"):
        return True
    # Ambiguous output -> don't block; log for tuning.
    logger.debug("[voice judge] ambiguous answer %r, fail-open", raw)
    return True


def generate_tweet(cfg: dict, format_key: str, original_tweet: str,
                   length_tier: str = "MEDIUM", recent_posts: list[str] | None = None,
                   enabled_topics: list[str] | None = None) -> str:
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
    return _generate_with_retries(
        cfg, system, user,
        length_tier=length_tier, dont_text=dont, voice=voice,
        label="generate_tweet",
    )


def generate_quote_comment(cfg: dict, original_tweet: str,
                           recent_posts: list[str] | None = None,
                           enabled_topics: list[str] | None = None,
                           image_b64_list: list[tuple[str, str]] | None = None) -> str:
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
    if images:
        call_fn = lambda u: _call_llm_with_images_for_generation(cfg, system, u, images)
    else:
        call_fn = lambda u: _call_llm(cfg, system, u)
    return _generate_with_retries(
        cfg, system, user,
        length_tier="SHORT", dont_text=dont, voice=voice,
        call_fn=call_fn, label="generate_quote",
    )


def generate_reply_comment(cfg: dict, original_tweet: str, length_tier: str, tone: str,
                           recent_posts: list[str] | None = None,
                           post_type: str = "", reply_strategy: str = "",
                           existing_replies: list[str] | None = None,
                           positions: list[dict] | None = None,
                           enabled_topics: list[str] | None = None,
                           image_b64_list: list[tuple[str, str]] | None = None) -> str:
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
    if images:
        call_fn = lambda u: _call_llm_with_images_for_generation(cfg, system, u, images)
    else:
        call_fn = lambda u: _call_llm(cfg, system, u)
    return _generate_with_retries(
        cfg, system, user,
        length_tier=length_tier, dont_text=dont, voice=voice,
        call_fn=call_fn, label="generate_reply",
    )


def _is_safe_project_comment(text: str) -> bool:
    lower = text.lower()
    return not any(word in lower for word in PROJECT_BANNED_WORDS)


def generate_project_comment(project_name: str, recent_comments: list[str] | None = None) -> str:
    short_name = project_name.lstrip("@").split()[0]
    recent = set(recent_comments or [])
    candidates = list(PROJECT_COMMENT_TEMPLATES)
    random.shuffle(candidates)
    for template in candidates:
        text = template.format(project=short_name)
        if text in recent:
            continue
        if _is_safe_project_comment(text):
            return text
    fallback = random.choice(PROJECT_COMMENT_TEMPLATES)
    return fallback.format(project=short_name)


def generate_smart_project_comment(cfg: dict, post_text: str, post_author: str,
                                   top_replies: list[str], project_name: str) -> str | None:
    if not _active_api_key(cfg):
        return None
    system, user = build_project_reply_prompt(
        post_text=post_text, post_author=post_author,
        top_replies=top_replies,
        project_name=cfg.get("project_name") or project_name,
        project_about=cfg.get("project_about", ""),
        project_do=cfg.get("project_do", ""),
        project_dont=cfg.get("project_dont", ""),
    )
    dont = cfg.get("project_dont", "")
    for _ in range(MAX_RETRIES):
        raw = _call_llm(cfg, system, user)
        text = raw.strip().strip('"').strip("'").strip()
        if not text:
            continue
        if not _is_safe_project_comment(text):
            continue
        if len(text) > 200:
            continue
        from app.content.validator import _check_dont_rules
        violated, line = _check_dont_rules(text, dont)
        if violated:
            logger.info("[generate_project] Rejected by Don't rule: %s", line)
            continue
        return text
    return None


def generate_degen_tweet(cfg: dict, format_key: str, original_tweet: str,
                         recent_posts: list[str] | None = None) -> str:
    voice = cfg.get("degen_voice_description", "")
    dont = cfg.get("degen_dont", "")
    system, user = build_degen_tweet_prompt(
        voice, format_key, original_tweet,
        cfg.get("degen_do", ""), dont,
        recent_posts=recent_posts,
    )
    return _generate_with_retries(
        cfg, system, user,
        length_tier="MEDIUM", dont_text=dont, voice=voice,
        label="generate_degen_tweet",
    )


def generate_degen_quote_comment(cfg: dict, original_tweet: str,
                                 recent_posts: list[str] | None = None) -> str:
    voice = cfg.get("degen_voice_description", "")
    dont = cfg.get("degen_dont", "")
    system, user = build_degen_quote_comment_prompt(
        voice, original_tweet,
        cfg.get("degen_do", ""), dont,
        recent_posts=recent_posts,
    )
    return _generate_with_retries(
        cfg, system, user,
        length_tier="SHORT", dont_text=dont, voice=voice,
        label="generate_degen_quote",
    )


def generate_degen_reply_comment(cfg: dict, original_tweet: str, length_tier: str, tone: str,
                                 recent_posts: list[str] | None = None,
                                 post_type: str = "", reply_strategy: str = "",
                                 existing_replies: list[str] | None = None,
                                 positions: list[dict] | None = None) -> str:
    voice = cfg.get("degen_voice_description", "")
    dont = cfg.get("degen_dont", "")
    system, user = build_degen_reply_prompt(
        voice, original_tweet, length_tier, tone,
        cfg.get("degen_do", ""), dont,
        recent_posts=recent_posts,
        post_type=post_type, reply_strategy=reply_strategy,
        existing_replies=existing_replies, positions=positions,
    )
    return _generate_with_retries(
        cfg, system, user,
        length_tier=length_tier, dont_text=dont, voice=voice,
        label="generate_degen_reply",
    )


def generate_thread(cfg: dict, thread_format_key: str, original_tweet: str,
                    recent_posts: list[str] | None = None,
                    enabled_topics: list[str] | None = None) -> list[str] | None:
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
    _clear_rejection()
    last_reason = ""
    last_raw = ""
    for attempt in range(MAX_RETRIES):
        prompt = _user_with_feedback(user, last_reason, last_raw)
        raw = _call_llm(cfg, system, prompt)
        last_raw = raw or ""
        tweets = [t.strip() for t in (raw or "").split("---") if t.strip()]
        if len(tweets) < 2:
            last_reason = f"only {len(tweets)} thread segment(s), need >=2 separated by ---"
            _record_rejection(last_reason)
            logger.info("[generate_thread] attempt %d: %s", attempt + 1, last_reason)
            continue
        validated: list[str] = []
        rejected_reason = ""
        all_passed = True
        for tweet in tweets:
            result = validate_and_fix(tweet, "MEDIUM", dont_text=dont, voice=voice)
            if not result.passed:
                all_passed = False
                rejected_reason = result.reason
                break
            validated.append(result.text)
        if not all_passed or len(validated) < 2:
            last_reason = rejected_reason or "thread validation failed"
            _record_rejection(last_reason)
            logger.info("[generate_thread] attempt %d rejected: %s", attempt + 1, last_reason)
            continue
        if use_voice_judge and voice and not _passes_voice_judge(cfg, "\n\n".join(validated), voice):
            last_reason = "voice judge: thread does not match the configured voice"
            _record_rejection(last_reason)
            logger.info("[generate_thread] attempt %d rejected by voice judge", attempt + 1)
            continue
        return validated
    logger.warning("[generate_thread] all %d attempts rejected (last: %s)", MAX_RETRIES, last_reason)
    return None


def classify_post_with_llm(cfg: dict, post_text: str) -> dict | None:
    if not _active_api_key(cfg):
        return None
    system, user = build_classification_prompt(post_text)
    try:
        raw = _call_llm(cfg, system, user)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        if "type" in result and "reply_strategy" in result:
            return result
    except (json.JSONDecodeError, KeyError, IndexError):
        pass
    return None


def _match_enabled_topic_label(raw: object, enabled_topics: list[str]) -> str | None:
    """Map LLM output to an exact enabled topic label (handles minor spelling / spacing drift)."""
    if raw is None:
        return None
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
    for t in enabled_topics:
        tl = t.lower()
        if tl in s_lower or s_lower in tl:
            return t
    return None


def batch_classify_topics(
    cfg: dict,
    posts: list[dict],
    enabled_topics: list[str],
) -> dict[str, str]:
    """Analyze each post and assign at most one category from enabled topics (one LLM call).

    Returns {post_url: exact_topic_label} only for posts the model assigns to a category.
    Politics, geopolitics, off-topic, etc. → omitted (no key).
    """
    if not _active_api_key(cfg) or not posts or not enabled_topics:
        return {}

    topics_lines = "\n".join(f"- {t}" for t in enabled_topics)
    numbered = []
    url_index: dict[int, str] = {}
    for i, p in enumerate(posts, 1):
        text = (p.get("text") or "")[:400]
        url_index[i] = p.get("url", "")
        numbered.append(f"{i}. {text}")
    tweets_block = "\n".join(numbered)

    political_rule = ""
    if cfg.get("exclude_political_timeline", True):
        political_rule = (
            "\n- Do NOT assign any topic to domestic or foreign politics, elections, wars, "
            "geopolitics, or breaking news about governments — omit those tweet numbers.\n"
        )

    narrow_rule = (
        "\n- These are the ONLY categories this user cares about. "
        "Only assign a label when the tweet genuinely fits one of them. "
        "If unsure or only a weak match, use null.\n"
    )

    system = (
        "You categorize X/Twitter posts. For EACH numbered tweet:\n"
        "1. First decide what the tweet is REALLY about (politics, crypto prices, sports, tech, AI, startups, etc.).\n"
        "2. Then check: does that real category match one of the user's enabled topics below?\n"
        "3. If yes → output the EXACT matching topic string. If no → output null.\n\n"
        "DO NOT force-fit. A tweet about elections is politics even if the user has 'AI / ML tools' enabled. "
        "A tweet about Bitcoin price is crypto trading, not 'Startup / founder life'. "
        "Only match when the tweet genuinely belongs to the topic.\n\n"
        "The user's enabled topics (use these strings verbatim when matching):\n"
        f"{topics_lines}\n"
        f"{political_rule}"
        f"{narrow_rule}"
        "Output rules:\n"
        "- Return ONLY a JSON object. Keys are tweet numbers as strings (\"1\", \"2\", ...).\n"
        "- Values are either the EXACT topic string from the list above, or null.\n"
        "- Do not invent new category names.\n"
        "- No markdown fences, no commentary.\n"
        'Example: {"1": "AI / ML tools", "2": null, "3": null, "4": "Frontend / UI / UX"}'
    )
    user = f"Categorize each tweet:\n\n{tweets_block}"

    # Enough room for ~30 short labels + nulls
    n_posts = len(posts)
    max_out = min(4096, 256 + n_posts * 80)

    try:
        raw = _call_llm(cfg, system, user, temperature=0.15, max_tokens=max_out)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        mapping = json.loads(raw)
        result: dict[str, str] = {}
        for idx_str, topic_raw in mapping.items():
            try:
                idx = int(idx_str)
            except (TypeError, ValueError):
                continue
            url = url_index.get(idx, "")
            topic = _match_enabled_topic_label(topic_raw, enabled_topics)
            if url and topic:
                result[url] = topic
        return result
    except (json.JSONDecodeError, KeyError, ValueError, IndexError) as exc:
        logger.warning("[batch_classify_topics] LLM response parse failed: %s", exc)
        return {}


def extract_position(cfg: dict, posted_text: str) -> dict | None:
    if not _active_api_key(cfg):
        return None
    system, user = build_position_extraction_prompt(posted_text)
    try:
        raw = _call_llm(cfg, system, user)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw)
        if result.get("topic") and result.get("stance"):
            return result
    except (json.JSONDecodeError, KeyError, IndexError):
        pass
    return None


def check_image_relevance_with_vision(cfg: dict, image_b64: str, generated_text: str,
                                      mime_type: str = "image/jpeg") -> bool:
    """Return True only when vision confirms relevance. Fail-closed on any error/missing key
    so we never attach a possibly-irrelevant image to our own post."""
    if not _active_api_key(cfg):
        return False
    system = "You verify whether an image is relevant to a tweet. Answer ONLY 'YES' or 'NO'."
    user = f'Does this image relate to the following tweet text? Answer YES or NO.\nTweet: "{generated_text}"'
    try:
        raw = _call_llm_with_image(cfg, system, user, image_b64, mime_type)
        return "YES" in raw.upper()
    except Exception as exc:
        logger.warning("[vision] relevance check failed, skipping image: %s", exc)
        return False
