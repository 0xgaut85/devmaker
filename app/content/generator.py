"""Unified LLM interface supporting OpenAI and Anthropic — adapted for web backend."""

import base64
import json
import random

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


def _call_llm(cfg: dict, system: str, user: str) -> str:
    """Call the configured LLM provider and return raw text.
    cfg is a dict with llm_provider, openai_api_key, anthropic_api_key, etc."""
    if cfg.get("llm_provider") == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=cfg.get("anthropic_api_key", ""))
        response = client.messages.create(
            model=_active_model(cfg),
            max_tokens=1024,
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
            max_tokens=1024,
            temperature=0.9,
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


def generate_tweet(cfg: dict, format_key: str, original_tweet: str,
                   length_tier: str = "MEDIUM", recent_posts: list[str] | None = None) -> str:
    system, user = build_tweet_rephrase_prompt(
        voice=cfg.get("voice_description", ""),
        bad_examples=cfg.get("bad_examples", ""),
        good_examples=cfg.get("good_examples", ""),
        format_key=format_key,
        original_tweet=original_tweet,
        recent_posts=recent_posts,
    )
    result = None
    for _ in range(MAX_RETRIES):
        raw = _call_llm(cfg, system, user)
        result = validate_and_fix(raw, length_tier)
        if result.passed:
            return result.text
    return result.text


def generate_quote_comment(cfg: dict, original_tweet: str,
                           recent_posts: list[str] | None = None) -> str:
    system, user = build_quote_comment_prompt(
        voice=cfg.get("voice_description", ""),
        bad_examples=cfg.get("bad_examples", ""),
        good_examples=cfg.get("good_examples", ""),
        original_tweet=original_tweet,
        recent_posts=recent_posts,
    )
    result = None
    for _ in range(MAX_RETRIES):
        raw = _call_llm(cfg, system, user)
        result = validate_and_fix(raw, "SHORT")
        if result.passed:
            return result.text
    return result.text


def generate_reply_comment(cfg: dict, original_tweet: str, length_tier: str, tone: str,
                           recent_posts: list[str] | None = None,
                           post_type: str = "", reply_strategy: str = "",
                           existing_replies: list[str] | None = None,
                           positions: list[dict] | None = None) -> str:
    system, user = build_reply_comment_prompt(
        voice=cfg.get("voice_description", ""),
        bad_examples=cfg.get("bad_examples", ""),
        good_examples=cfg.get("good_examples", ""),
        original_tweet=original_tweet,
        length_tier=length_tier, tone=tone,
        recent_posts=recent_posts,
        post_type=post_type, reply_strategy=reply_strategy,
        existing_replies=existing_replies, positions=positions,
    )
    result = None
    for _ in range(MAX_RETRIES):
        raw = _call_llm(cfg, system, user)
        result = validate_and_fix(raw, length_tier)
        if result.passed:
            return result.text
    return result.text


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
    result = None
    for _ in range(MAX_RETRIES):
        raw = _call_llm(cfg, system, user)
        result = validate_and_fix(raw, "MEDIUM")
        if result.passed:
            return result.text
    return result.text


def generate_degen_quote_comment(cfg: dict, original_tweet: str,
                                 recent_posts: list[str] | None = None) -> str:
    voice = cfg.get("degen_voice_description", "")
    system, user = build_degen_quote_comment_prompt(
        voice, original_tweet,
        cfg.get("degen_do", ""), cfg.get("degen_dont", ""),
        recent_posts=recent_posts,
    )
    result = None
    for _ in range(MAX_RETRIES):
        raw = _call_llm(cfg, system, user)
        result = validate_and_fix(raw, "SHORT")
        if result.passed:
            return result.text
    return result.text


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
    result = None
    for _ in range(MAX_RETRIES):
        raw = _call_llm(cfg, system, user)
        result = validate_and_fix(raw, length_tier)
        if result.passed:
            return result.text
    return result.text


def generate_thread(cfg: dict, thread_format_key: str, original_tweet: str,
                    recent_posts: list[str] | None = None) -> list[str] | None:
    system, user = build_thread_prompt(
        voice=cfg.get("voice_description", ""),
        bad_examples=cfg.get("bad_examples", ""),
        good_examples=cfg.get("good_examples", ""),
        thread_format_key=thread_format_key,
        original_tweet=original_tweet,
        recent_posts=recent_posts,
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
