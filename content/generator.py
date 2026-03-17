"""Unified LLM interface supporting OpenAI and Anthropic."""

import base64
import json
import random

from content.prompts import (
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
from content.rules import PROJECT_COMMENT_TEMPLATES, PROJECT_BANNED_WORDS
from content.validator import validate_and_fix, ValidationResult
from core.config import Config

MAX_RETRIES = 3


def _call_llm(config: Config, system: str, user: str) -> str:
    """Call the configured LLM provider and return raw text."""
    if config.llm_provider == "anthropic":
        import anthropic

        client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        response = client.messages.create(
            model=config.active_model(),
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text
    else:
        import openai

        client = openai.OpenAI(api_key=config.openai_api_key)
        response = client.chat.completions.create(
            model=config.active_model(),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=1024,
            temperature=0.9,
        )
        return response.choices[0].message.content


def _call_llm_with_image(config: Config, system: str, user: str, image_path: str) -> str:
    """Call the LLM with an image attachment for vision tasks."""
    import mimetypes

    mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    if config.llm_provider == "anthropic":
        import anthropic

        client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        response = client.messages.create(
            model=config.active_model(),
            max_tokens=256,
            system=system,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": image_data}},
                    {"type": "text", "text": user},
                ],
            }],
        )
        return response.content[0].text
    else:
        import openai

        client = openai.OpenAI(api_key=config.openai_api_key)
        response = client.chat.completions.create(
            model=config.active_model(),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_data}"}},
                    {"type": "text", "text": user},
                ]},
            ],
            max_tokens=256,
        )
        return response.choices[0].message.content


def generate_tweet(
    config: Config,
    format_key: str,
    original_tweet: str,
    length_tier: str = "MEDIUM",
    recent_posts: list[str] | None = None,
) -> str:
    """Generate a rephrased tweet. Retries on validation failure."""
    system, user = build_tweet_rephrase_prompt(
        voice=config.voice_description,
        bad_examples=config.bad_examples,
        good_examples=config.good_examples,
        format_key=format_key,
        original_tweet=original_tweet,
        recent_posts=recent_posts,
    )
    for attempt in range(MAX_RETRIES):
        raw = _call_llm(config, system, user)
        result = validate_and_fix(raw, length_tier)
        if result.passed:
            return result.text
    return result.text  # return last attempt even if imperfect


def generate_quote_comment(
    config: Config,
    original_tweet: str,
    recent_posts: list[str] | None = None,
) -> str:
    """Generate a quote RT comment. Retries on validation failure."""
    system, user = build_quote_comment_prompt(
        voice=config.voice_description,
        bad_examples=config.bad_examples,
        good_examples=config.good_examples,
        original_tweet=original_tweet,
        recent_posts=recent_posts,
    )
    for attempt in range(MAX_RETRIES):
        raw = _call_llm(config, system, user)
        result = validate_and_fix(raw, "SHORT")
        if result.passed:
            return result.text
    return result.text


def generate_reply_comment(
    config: Config,
    original_tweet: str,
    length_tier: str,
    tone: str,
    recent_posts: list[str] | None = None,
    post_type: str = "",
    reply_strategy: str = "",
    existing_replies: list[str] | None = None,
    positions: list[dict] | None = None,
) -> str:
    """Generate a reply comment. Retries on validation failure."""
    system, user = build_reply_comment_prompt(
        voice=config.voice_description,
        bad_examples=config.bad_examples,
        good_examples=config.good_examples,
        original_tweet=original_tweet,
        length_tier=length_tier,
        tone=tone,
        recent_posts=recent_posts,
        post_type=post_type,
        reply_strategy=reply_strategy,
        existing_replies=existing_replies,
        positions=positions,
    )
    for attempt in range(MAX_RETRIES):
        raw = _call_llm(config, system, user)
        result = validate_and_fix(raw, length_tier)
        if result.passed:
            return result.text
    return result.text


# --- Project Farming ---

def _is_safe_project_comment(text: str) -> bool:
    """Check that a project comment contains no banned words."""
    lower = text.lower()
    return not any(word in lower for word in PROJECT_BANNED_WORDS)


def generate_project_comment(
    project_name: str,
    recent_comments: list[str] | None = None,
) -> str:
    """Pick a random short engagement comment, avoiding recent duplicates."""
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


def generate_smart_project_comment(
    config: Config,
    post_text: str,
    post_author: str,
    top_replies: list[str],
    project_name: str,
) -> str | None:
    """Use LLM to generate a context-aware reply-guy comment.
    Reads the post and existing replies to match the vibe.
    Returns None if no API key is configured (caller should fall back to templates).
    """
    if not config.active_api_key():
        return None

    system, user = build_project_reply_prompt(
        post_text=post_text,
        post_author=post_author,
        top_replies=top_replies,
        project_name=config.project_name or project_name,
        project_about=config.project_about,
        project_do=config.project_do,
        project_dont=config.project_dont,
    )

    for _ in range(MAX_RETRIES):
        raw = _call_llm(config, system, user)
        text = raw.strip().strip('"').strip("'").strip()
        if not text:
            continue
        if not _is_safe_project_comment(text):
            continue
        if len(text) > 200:
            continue
        return text

    return None


# --- Degen Farming ---

def generate_degen_tweet(
    config: Config,
    format_key: str,
    original_tweet: str,
    recent_posts: list[str] | None = None,
) -> str:
    """Generate a degen-style rephrased tweet."""
    voice = config.degen_voice_description or ""
    system, user = build_degen_tweet_prompt(voice, format_key, original_tweet, config.degen_do, config.degen_dont, recent_posts=recent_posts)
    for attempt in range(MAX_RETRIES):
        raw = _call_llm(config, system, user)
        result = validate_and_fix(raw, "MEDIUM")
        if result.passed:
            return result.text
    return result.text


def generate_degen_quote_comment(
    config: Config,
    original_tweet: str,
    recent_posts: list[str] | None = None,
) -> str:
    """Generate a degen-style quote RT comment."""
    voice = config.degen_voice_description or ""
    system, user = build_degen_quote_comment_prompt(voice, original_tweet, config.degen_do, config.degen_dont, recent_posts=recent_posts)
    for attempt in range(MAX_RETRIES):
        raw = _call_llm(config, system, user)
        result = validate_and_fix(raw, "SHORT")
        if result.passed:
            return result.text
    return result.text


def generate_degen_reply_comment(
    config: Config,
    original_tweet: str,
    length_tier: str,
    tone: str,
    recent_posts: list[str] | None = None,
    post_type: str = "",
    reply_strategy: str = "",
    existing_replies: list[str] | None = None,
    positions: list[dict] | None = None,
) -> str:
    """Generate a degen-style reply comment."""
    voice = config.degen_voice_description or ""
    system, user = build_degen_reply_prompt(
        voice, original_tweet, length_tier, tone,
        config.degen_do, config.degen_dont,
        recent_posts=recent_posts,
        post_type=post_type,
        reply_strategy=reply_strategy,
        existing_replies=existing_replies,
        positions=positions,
    )
    for attempt in range(MAX_RETRIES):
        raw = _call_llm(config, system, user)
        result = validate_and_fix(raw, length_tier)
        if result.passed:
            return result.text
    return result.text


def generate_thread(
    config: Config,
    thread_format_key: str,
    original_tweet: str,
    recent_posts: list[str] | None = None,
) -> list[str] | None:
    """Generate a multi-tweet thread. Returns list of tweets or None on failure."""
    system, user = build_thread_prompt(
        voice=config.voice_description,
        bad_examples=config.bad_examples,
        good_examples=config.good_examples,
        thread_format_key=thread_format_key,
        original_tweet=original_tweet,
        recent_posts=recent_posts,
    )
    for _ in range(MAX_RETRIES):
        raw = _call_llm(config, system, user)
        tweets = [t.strip() for t in raw.split("---") if t.strip()]
        if len(tweets) >= 2:
            validated = []
            for tweet in tweets:
                result = validate_and_fix(tweet, "MEDIUM")
                validated.append(result.text)
            return validated
    return None


# --- LLM Classification ---

def classify_post_with_llm(config: Config, post_text: str) -> dict | None:
    """Use LLM to classify post tone, type, and suggest reply strategy.
    Returns dict with type/tone/intent/reply_strategy or None on failure."""
    if not config.active_api_key():
        return None
    system, user = build_classification_prompt(post_text)
    try:
        raw = _call_llm(config, system, user)
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


# --- Position Extraction ---

def extract_position(config: Config, posted_text: str) -> dict | None:
    """Extract topic and stance from a posted tweet.
    Returns dict with topic/stance or None."""
    if not config.active_api_key():
        return None
    system, user = build_position_extraction_prompt(posted_text)
    try:
        raw = _call_llm(config, system, user)
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


# --- Vision Image Check ---

def check_image_relevance_with_vision(config: Config, image_path: str, generated_text: str) -> bool:
    """Use vision model to check if an image relates to the tweet text."""
    if not config.active_api_key():
        return True
    system = "You verify whether an image is relevant to a tweet. Answer ONLY 'YES' or 'NO'."
    user = f'Does this image relate to the following tweet text? Answer YES or NO.\nTweet: "{generated_text}"'
    try:
        raw = _call_llm_with_image(config, system, user, image_path)
        return "YES" in raw.upper()
    except Exception:
        return True
