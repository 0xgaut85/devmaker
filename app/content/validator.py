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


def is_duplicate(
    text: str,
    recent_texts: list[str],
    *,
    threshold: float = 0.55,
    short_threshold: float = 0.85,
) -> bool:
    """Single canonical dedup check used by every generator + the orchestrator.

    For very short posts (<3 unique non-stopword tokens) we used to bypass entirely,
    which let generic "ship ship ship" style replies repeat forever. Now we still
    check exact-or-near-exact match for shorts using a strict ratio.
    """
    if not recent_texts:
        return False
    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    new_words = _word_set(text)
    if len(new_words) < 3:
        for prev in recent_texts:
            prev_normalized = (prev or "").strip().lower()
            if not prev_normalized:
                continue
            if normalized == prev_normalized:
                return True
            prev_words = _word_set(prev)
            if not prev_words:
                continue
            intersection = len(new_words & prev_words)
            union = len(new_words | prev_words)
            if union > 0 and intersection / union >= short_threshold:
                return True
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


# Number of leading NON-stopword tokens to fingerprint. 2 is the sweet spot:
# small enough to catch stylistic opener patterns ("hot take", "pro tip", "real
# talk") even when the rest of the post differs, but large enough to avoid
# blocking on a single shared first word like "Postgres" or "AI".
_OPENER_NSW_TOKENS = 2

_OPENER_TOKEN_RE = re.compile(r"[a-z0-9']+")


def _opener_fingerprint(text: str) -> tuple[str, ...]:
    """Return the first ``_OPENER_NSW_TOKENS`` non-stopword word tokens of
    ``text``, lowercased and punctuation-stripped.

    "Hot take: postgres beats mongo" -> ("hot", "take")
    "I think rust beats go"          -> ("think", "rust")
    "Pro tip — always profile first" -> ("pro", "tip")

    Stopword stripping is what makes the fingerprint robust to natural English
    filler ("I", "the", "a", "is") that would otherwise inflate two unrelated
    openers into a false match.
    """
    if not text:
        return ()
    tokens = _OPENER_TOKEN_RE.findall(text.lower())
    out: list[str] = []
    for t in tokens:
        if t in _STOPWORDS:
            continue
        out.append(t)
        if len(out) >= _OPENER_NSW_TOKENS:
            break
    return tuple(out)


def has_repeated_opener(text: str, recent_texts: list[str]) -> bool:
    """True when ``text`` shares its non-stopword opener fingerprint with any
    of ``recent_texts``.

    Catches the "4 'Hot take:' tweets in a row" failure mode where the body
    content differs (so :func:`is_duplicate` passes) but the opener pattern is
    identical. We compare against the full ``recent_texts`` list because the
    caller already passes the trimmed last-N window.
    """
    fp = _opener_fingerprint(text)
    if len(fp) < _OPENER_NSW_TOKENS:
        return False
    for prev in recent_texts or []:
        if fp == _opener_fingerprint(prev):
            return True
    return False


class ValidationResult:
    def __init__(self, text: str, passed: bool, reason: str = ""):
        self.text = text
        self.passed = passed
        self.reason = reason


# Broad emoji coverage: pictographs, dingbats, symbols, transport, regional indicators.
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002700-\U000027BF"  # dingbats
    "\U0001F1E6-\U0001F1FF"  # regional indicators (flags)
    "]",
    flags=re.UNICODE,
)

# Only catch genuine persona breaks. Brand names (claude, openai, anthropic,
# chatgpt) are intentionally NOT here — they are valid topics on tech Twitter
# and rejecting them creates infinite retries when the source post is about AI.
_AI_LEAK_PATTERNS = [
    r"\bas an ai\b",
    r"\bas a language model\b",
    r"\bi'?m an? (?:ai|assistant|language model|chatbot)\b",
    r"\bi am an? (?:ai|assistant|language model|chatbot)\b",
    r"\bi cannot (?:help|assist|provide|generate|fulfill)\b",
    r"\bi can'?t (?:help|assist|provide|generate|fulfill)\b",
    r"\bi'?m sorry,? (?:but )?i (?:can|cannot|am unable|won'?t)\b",
]


def _check_dont_rules(text: str, dont_text: str) -> tuple[bool, str]:
    """Return (violated, line_that_triggered).

    Parses each line of `dont_text` and runs deterministic matchers. The first
    matched violation wins.
    """
    if not dont_text or not dont_text.strip():
        return False, ""
    raw = text or ""
    lower = raw.lower()
    for raw_line in dont_text.splitlines():
        line = raw_line.strip().lstrip("-*•").strip()
        if not line:
            continue
        l = line.lower()

        # Emoji
        if (
            re.search(r"\b(no|zero|never|0)\s+emoji", l)
            or re.search(r"emoji.*(forbidden|banned|never|none|allowed)", l)
            or re.search(r"don'?t\s+(?:use|include)\s+emoji", l)
        ):
            if _EMOJI_RE.search(raw):
                return True, line
            continue

        # Hashtags
        if re.search(r"\bno\s+hashtags?\b", l) or re.search(r"don'?t\s+(?:use|include)\s+hashtags?", l):
            if re.search(r"#\w", raw):
                return True, line
            continue

        # Em dashes
        if re.search(r"\bno\s+em[- ]?dash", l) or re.search(r"don'?t\s+(?:use|include)\s+em[- ]?dash", l):
            if "—" in raw or "–" in raw:
                return True, line
            continue

        # ALL CAPS
        if re.search(r"\bno\s+(?:all[- ]?)?caps\b", l) or re.search(r"don'?t\s+(?:shout|yell)", l):
            if re.findall(r"\b[A-Z]{4,}\b", raw):
                return True, line
            continue

        # Questions
        if re.search(r"\bno\s+questions?\b", l) or re.search(r"don'?t\s+ask\s+questions?", l):
            if "?" in raw:
                return True, line
            continue

        # Exclamation marks
        if re.search(r"\bno\s+exclamation", l):
            if "!" in raw:
                return True, line
            continue

        # Links / URLs
        if re.search(r"\bno\s+(?:links?|urls?)\b", l):
            if re.search(r"https?://", raw, re.IGNORECASE):
                return True, line
            continue

        # NOTE: We deliberately do NOT auto-ban quoted substrings. Users use
        # quotes for emphasis ("tech aspect") far more often than to mark a
        # forbidden literal, and false positives loop the generator forever.
        # Explicit per-rule matchers above handle the structural bans.

        # Generic "no <word>" / "avoid <word>" / "don't say <word>" — only when
        # the remainder is short and looks like an actual phrase (<=4 words),
        # otherwise we'd reject any tweet containing a common word.
        m = re.match(r"(?:no|avoid|don'?t\s+(?:say|use|include|write))\s+(.+)", l)
        if m:
            phrase = m.group(1).strip().strip(".,;:!?")
            words = phrase.split()
            # Skip filler like "at all", "ever", "please" so 'no emojis at all' -> phrase 'emojis'
            while words and words[-1].lower() in {"at", "all", "ever", "please", "anymore", "now"}:
                words.pop()
            phrase = " ".join(words)
            if phrase and 1 <= len(words) <= 4 and re.search(rf"\b{re.escape(phrase)}\b", lower):
                return True, line
            continue

    return False, ""


def _check_ai_leak(text: str) -> tuple[bool, str]:
    lower = (text or "").lower()
    for pat in _AI_LEAK_PATTERNS:
        if re.search(pat, lower):
            return True, pat
    return False, ""


def validate_and_fix(
    text: str,
    length_tier: str | None = None,
    dont_text: str = "",
    voice: str = "",
) -> ValidationResult:
    original = text
    text = text.strip()

    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        text = text[1:-1].strip()

    # Em-dash normalisation only happens when the user has NOT explicitly banned em-dashes.
    # If they did, we want the raw em-dash to remain visible to the Don't checker so it rejects.
    em_dash_banned = bool(dont_text) and bool(re.search(r"\bno\s+em[- ]?dash", dont_text, re.IGNORECASE))
    if not em_dash_banned:
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

    # Reject empty reaction-style posts ONLY for original tweets / quotes — short
    # replies are allowed to be reactions because that's how replies actually work.
    if length_tier and length_tier != "SHORT":
        _REACTION_PATTERNS = [
            r"^this hits",
            r"^needed (this|to hear)\.?$",
            r"^felt this\.?$",
            r"^real talk right here\.?$",
            r"^say it louder\.?$",
        ]
        for pat in _REACTION_PATTERNS:
            if re.match(pat, lower):
                return ValidationResult(text, False, f"Reaction-style post: {pat}")

    # Substance floor: only enforced for non-SHORT tiers.
    if length_tier and length_tier != "SHORT":
        if len(text) < 30 and "?" not in text:
            return ValidationResult(text, False, f"Too short to have substance: {len(text)} chars")

    # NOTE: We deliberately do NOT auto-inject "\n\n" between sentences here.
    # The previous version did, which forced every multi-sentence MEDIUM/LONG/XL
    # post into the same "sentence\n\nsentence\n\nsentence" layout — readers
    # could spot the bot at a glance just by scrolling. The prompt now picks a
    # random visual structure per generation (see prompts._structure_block);
    # respect what the LLM produces instead of overriding it.

    _LENGTH_SLACK = 40
    if length_tier and length_tier in LENGTH_TIERS:
        tier = LENGTH_TIERS[length_tier]
        char_count = len(text)
        max_allowed = tier["max"] + _LENGTH_SLACK
        if char_count > max_allowed:
            return ValidationResult(
                text, False,
                f"Too long for {length_tier}: {char_count} chars (max ~{max_allowed})",
            )

    # User-defined Don't rules — hard rejection so the generator retries.
    violated, line = _check_dont_rules(text, dont_text)
    if violated:
        return ValidationResult(text, False, f"Violates Don't rule: {line}")

    # If a custom voice is configured, persona leaks are unacceptable.
    if voice and voice.strip():
        leaked, pat = _check_ai_leak(text)
        if leaked:
            return ValidationResult(text, False, f"Persona/AI leak: {pat}")

    return ValidationResult(text, True)
