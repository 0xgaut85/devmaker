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


def generate_tweet(cfg: dict, format_key: str, original_tweet: str,
                   length_tier: str = "MEDIUM", recent_posts: list[str] | None = None,
                   enabled_topics: list[str] | None = None) -> str:
    system, user = build_tweet_rephrase_prompt(
        voice=cfg.get("voice_description", ""),
        bad_examples=cfg.get("bad_examples", ""),
        good_examples=cfg.get("good_examples", ""),
        format_key=format_key,
        original_tweet=original_tweet,
        recent_posts=recent_posts,
        cfg=cfg,
        enabled_topics=enabled_topics,
    )
    for attempt in range(MAX_RETRIES):
        raw = _call_llm(cfg, system, user)
        result = validate_and_fix(raw, length_tier)
        if result.passed:
            return result.text
        logger.info("[generate_tweet] Attempt %d rejected: %s | %.80s", attempt + 1, result.reason, raw)
    logger.warning("[generate_tweet] All %d attempts rejected by validator", MAX_RETRIES)
    return None


def generate_quote_comment(cfg: dict, original_tweet: str,
                           recent_posts: list[str] | None = None,
                           enabled_topics: list[str] | None = None,
                           image_b64_list: list[tuple[str, str]] | None = None) -> str:
    images = image_b64_list or []
    system, user = build_quote_comment_prompt(
        voice=cfg.get("voice_description", ""),
        bad_examples=cfg.get("bad_examples", ""),
        good_examples=cfg.get("good_examples", ""),
        original_tweet=original_tweet,
        recent_posts=recent_posts,
        cfg=cfg,
        enabled_topics=enabled_topics,
        has_images=bool(images),
    )
    call_fn = lambda: _call_llm_with_images_for_generation(cfg, system, user, images) if images else _call_llm(cfg, system, user)
    for attempt in range(MAX_RETRIES):
        raw = call_fn()
        result = validate_and_fix(raw, "SHORT")
        if result.passed:
            return result.text
        logger.info("[generate_quote] Attempt %d rejected: %s | %.80s", attempt + 1, result.reason, raw)
    logger.warning("[generate_quote] All %d attempts rejected by validator", MAX_RETRIES)
    return None


def generate_reply_comment(cfg: dict, original_tweet: str, length_tier: str, tone: str,
                           recent_posts: list[str] | None = None,
                           post_type: str = "", reply_strategy: str = "",
                           existing_replies: list[str] | None = None,
                           positions: list[dict] | None = None,
                           enabled_topics: list[str] | None = None,
                           image_b64_list: list[tuple[str, str]] | None = None) -> str:
    images = image_b64_list or []
    system, user = build_reply_comment_prompt(
        voice=cfg.get("voice_description", ""),
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
    )
    call_fn = lambda: _call_llm_with_images_for_generation(cfg, system, user, images) if images else _call_llm(cfg, system, user)
    for attempt in range(MAX_RETRIES):
        raw = call_fn()
        result = validate_and_fix(raw, length_tier)
        if result.passed:
            return result.text
        logger.info("[generate_reply] Attempt %d rejected: %s | %.80s", attempt + 1, result.reason, raw)
    logger.warning("[generate_reply] All %d attempts rejected by validator", MAX_RETRIES)
    return None


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
    for _ in range(MAX_RETRIES):
        raw = _call_llm(cfg, system, user)
        text = raw.strip().strip('"').strip("'").strip()
        if not text:
            continue
        if not _is_safe_project_comment(text):
            continue
        if len(text) > 200:
            continue
        return text
    return None


def generate_degen_tweet(cfg: dict, format_key: str, original_tweet: str,
                         recent_posts: list[str] | None = None) -> str:
    voice = cfg.get("degen_voice_description", "")
    system, user = build_degen_tweet_prompt(
        voice, format_key, original_tweet,
        cfg.get("degen_do", ""), cfg.get("degen_dont", ""),
        recent_posts=recent_posts,
    )
    for attempt in range(MAX_RETRIES):
        raw = _call_llm(cfg, system, user)
        result = validate_and_fix(raw, "MEDIUM")
        if result.passed:
            return result.text
        logger.info("[generate_degen_tweet] Attempt %d rejected: %s | %.80s", attempt + 1, result.reason, raw)
    logger.warning("[generate_degen_tweet] All %d attempts rejected by validator", MAX_RETRIES)
    return None


def generate_degen_quote_comment(cfg: dict, original_tweet: str,
                                 recent_posts: list[str] | None = None) -> str:
    voice = cfg.get("degen_voice_description", "")
    system, user = build_degen_quote_comment_prompt(
        voice, original_tweet,
        cfg.get("degen_do", ""), cfg.get("degen_dont", ""),
        recent_posts=recent_posts,
    )
    for attempt in range(MAX_RETRIES):
        raw = _call_llm(cfg, system, user)
        result = validate_and_fix(raw, "SHORT")
        if result.passed:
            return result.text
        logger.info("[generate_degen_quote] Attempt %d rejected: %s | %.80s", attempt + 1, result.reason, raw)
    logger.warning("[generate_degen_quote] All %d attempts rejected by validator", MAX_RETRIES)
    return None


def generate_degen_reply_comment(cfg: dict, original_tweet: str, length_tier: str, tone: str,
                                 recent_posts: list[str] | None = None,
                                 post_type: str = "", reply_strategy: str = "",
                                 existing_replies: list[str] | None = None,
                                 positions: list[dict] | None = None) -> str:
    voice = cfg.get("degen_voice_description", "")
    system, user = build_degen_reply_prompt(
        voice, original_tweet, length_tier, tone,
        cfg.get("degen_do", ""), cfg.get("degen_dont", ""),
        recent_posts=recent_posts,
        post_type=post_type, reply_strategy=reply_strategy,
        existing_replies=existing_replies, positions=positions,
    )
    for attempt in range(MAX_RETRIES):
        raw = _call_llm(cfg, system, user)
        result = validate_and_fix(raw, length_tier)
        if result.passed:
            return result.text
        logger.info("[generate_degen_reply] Attempt %d rejected: %s | %.80s", attempt + 1, result.reason, raw)
    logger.warning("[generate_degen_reply] All %d attempts rejected by validator", MAX_RETRIES)
    return None


def generate_thread(cfg: dict, thread_format_key: str, original_tweet: str,
                    recent_posts: list[str] | None = None,
                    enabled_topics: list[str] | None = None) -> list[str] | None:
    system, user = build_thread_prompt(
        voice=cfg.get("voice_description", ""),
        bad_examples=cfg.get("bad_examples", ""),
        good_examples=cfg.get("good_examples", ""),
        thread_format_key=thread_format_key,
        original_tweet=original_tweet,
        recent_posts=recent_posts,
        cfg=cfg,
        enabled_topics=enabled_topics,
    )
    for _ in range(MAX_RETRIES):
        raw = _call_llm(cfg, system, user)
        tweets = [t.strip() for t in raw.split("---") if t.strip()]
        if len(tweets) >= 2:
            validated = []
            for tweet in tweets:
                result = validate_and_fix(tweet, "MEDIUM")
                validated.append(result.text)
            return validated
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
    if not _active_api_key(cfg):
        return True
    system = "You verify whether an image is relevant to a tweet. Answer ONLY 'YES' or 'NO'."
    user = f'Does this image relate to the following tweet text? Answer YES or NO.\nTweet: "{generated_text}"'
    try:
        raw = _call_llm_with_image(cfg, system, user, image_b64, mime_type)
        return "YES" in raw.upper()
    except Exception:
        return True
