"""Post-generation validator. Catches common LLM mistakes before posting."""

import re
from content.rules import BANNED_PHRASES, BANNED_OPENERS, LENGTH_TIERS

_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "and",
    "in", "that", "it", "for", "on", "with", "as", "at", "by", "this", "i",
    "you", "we", "they", "he", "she", "but", "or", "not", "no", "so", "if",
    "my", "your", "our", "its", "do", "did", "has", "have", "had", "just",
    "can", "will", "would", "could", "should", "from", "about", "up", "out",
    "all", "been", "more", "when", "than", "then", "also", "into", "over",
})


def _word_set(text: str) -> set[str]:
    """Extract meaningful keywords from text."""
    words = set(re.findall(r"[a-z0-9]+", text.lower()))
    return words - _STOPWORDS


def is_too_similar(text: str, recent_texts: list[str], threshold: float = 0.55) -> bool:
    """Check if text is too similar to any recent text using Jaccard similarity."""
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
    """Validate and auto-fix generated text. Returns fixed text + pass/fail."""
    original = text
    text = text.strip()

    # Strip wrapping quotes the LLM sometimes adds
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        text = text[1:-1].strip()

    # Replace em dashes with commas
    text = text.replace("—", ", ")
    text = text.replace("–", ", ")
    text = re.sub(r",\s*,", ",", text)  # clean up double commas

    # Ensure first character is uppercase
    if text and text[0].islower():
        text = text[0].upper() + text[1:]

    # Check banned openers — these require regeneration
    lower = text.lower()
    for opener in BANNED_OPENERS:
        if lower.startswith(opener.lower()):
            return ValidationResult(text, False, f"Starts with banned opener: {opener}")

    # Check banned phrases — these require regeneration
    for phrase in BANNED_PHRASES:
        if phrase.lower() in lower:
            return ValidationResult(
                text, False, f"Contains banned phrase: {phrase}"
            )

    # For MEDIUM+ content, ensure line breaks exist
    if length_tier and length_tier in ("MEDIUM", "LONG", "XL"):
        sentences = re.split(r"(?<=[.!?])\s+", text)
        if len(sentences) > 2 and "\n" not in text:
            text = "\n\n".join(sentences)

    # Check length tier if specified
    if length_tier and length_tier in LENGTH_TIERS:
        tier = LENGTH_TIERS[length_tier]
        char_count = len(text)
        if length_tier == "SHORT" and char_count > tier["max"] * 2:
            return ValidationResult(text, False, f"Too long for SHORT: {char_count} chars")

    return ValidationResult(text, True)
