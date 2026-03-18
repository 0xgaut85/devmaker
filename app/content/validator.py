"""Post-generation validator. Catches common LLM mistakes before posting."""

import re
from app.content.rules import BANNED_PHRASES, BANNED_OPENERS, LENGTH_TIERS

_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "and",
    "in", "that", "it", "for", "on", "with", "as", "at", "by", "this", "i",
    "you", "we", "they", "he", "she", "but", "or", "not", "no", "so", "if",
    "my", "your", "our", "its", "do", "did", "has", "have", "had", "just",
    "can", "will", "would", "could", "should", "from", "about", "up", "out",
    "all", "been", "more", "when", "than", "then", "also", "into", "over",
})


def _word_set(text: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    return words - _STOPWORDS


def is_too_similar(text: str, recent_texts: list[str], threshold: float = 0.55) -> bool:
    if not recent_texts:
        return False
    new_words = _word_set(text)
    if len(new_words) < 3:
        return False
    for prev in recent_texts:
        prev_words = _word_set(prev)
        if not prev_words:
            continue
        intersection = len(new_words & prev_words)
        union = len(new_words | prev_words)
        if union > 0 and intersection / union >= threshold:
            return True
    return False


class ValidationResult:
    def __init__(self, text: str, passed: bool, reason: str = ""):
        self.text = text
        self.passed = passed
        self.reason = reason


def validate_and_fix(text: str, length_tier: str | None = None) -> ValidationResult:
    original = text
    text = text.strip()

    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        text = text[1:-1].strip()

    text = text.replace("—", ", ")
    text = text.replace("–", ", ")
    text = re.sub(r",\s*,", ",", text)

    if text and text[0].islower():
        text = text[0].upper() + text[1:]

    lower = text.lower()
    for opener in BANNED_OPENERS:
        if lower.startswith(opener.lower()):
            return ValidationResult(text, False, f"Starts with banned opener: {opener}")

    for phrase in BANNED_PHRASES:
        if phrase.lower() in lower:
            return ValidationResult(text, False, f"Contains banned phrase: {phrase}")

    # Reject empty reaction-style posts that reference something not visible
    _REACTION_PATTERNS = [
        r"^that'?s\s+(the|so|really|actually|literally)",
        r"^this hits",
        r"^needed (this|to hear)",
        r"^felt this",
        r"^real talk right here",
        r"^say it louder",
    ]
    for pat in _REACTION_PATTERNS:
        if re.match(pat, lower):
            return ValidationResult(text, False, f"Reaction-style post: {pat}")

    # Reject posts that are too short to have substance (under 30 chars with no question mark)
    if len(text) < 30 and "?" not in text:
        return ValidationResult(text, False, f"Too short to have substance: {len(text)} chars")

    if length_tier and length_tier in ("MEDIUM", "LONG", "XL"):
        sentences = re.split(r"(?<=[.!?])\s+", text)
        if len(sentences) > 2 and "\n" not in text:
            text = "\n\n".join(sentences)

    if length_tier and length_tier in LENGTH_TIERS:
        tier = LENGTH_TIERS[length_tier]
        char_count = len(text)
        if length_tier == "SHORT" and char_count > tier["max"] * 2:
            return ValidationResult(text, False, f"Too long for SHORT: {char_count} chars")

    return ValidationResult(text, True)
