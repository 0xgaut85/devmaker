"""Dynamic system prompt builder. Injects user voice + built-in rules."""

import random

from app.content.rules import (
    GRAMMAR_RULES,
    REPLY_GRAMMAR_RULES,
    ANTI_SLOP_RULES,
    FORMAT_CATALOG,
    DEGEN_FORMAT_CATALOG,
    LENGTH_TIERS,
    THREAD_FORMAT_CATALOG,
)


# --------------------------------------------------------------------------- #
#  Visual structure picker                                                    #
#                                                                             #
#  The single biggest "this is a bot" tell we shipped was: every multi-       #
#  sentence post came out as "sentence\n\nsentence\n\nsentence". A reader     #
#  could spot the bot just by scrolling, before reading a single word. The    #
#  fix is to pick ONE concrete visual structure per generation — weighted by  #
#  format/length so it still makes sense — and inject it into the prompt as   #
#  an explicit instruction the LLM follows, instead of letting the model      #
#  default to its own training-data favourite (which is sentence-per-line).   #
# --------------------------------------------------------------------------- #

_STRUCTURES: dict[str, str] = {
    "single_line":
        "STRUCTURE: One flowing sentence (or two short sentences run together). "
        "NO line breaks at all. NO blank lines.",
    "flowing_paragraph":
        "STRUCTURE: 2-3 sentences flowing together as ONE paragraph. "
        "Use periods and commas. Do NOT put each sentence on its own line. "
        "The whole post is one block of text.",
    "two_paragraphs":
        "STRUCTURE: Exactly TWO paragraphs separated by ONE blank line. "
        "Each paragraph is 1-3 sentences flowing together (NO internal line breaks within a paragraph). "
        "Think: setup paragraph, then payoff paragraph.",
    "line_broken":
        "STRUCTURE: Each sentence on its own line, with a blank line between them. "
        "Use this format ONLY for this post — it is a deliberate punch-up rhythm, not a default.",
    "multi_paragraph":
        "STRUCTURE: 3+ paragraphs separated by blank lines. "
        "Each paragraph is a coherent thought unit (NOT a single sentence). "
        "Sentences inside a paragraph flow together with periods and commas, not line breaks.",
}

# Per-format weights. A format with strong inherent layout (numbered list,
# one-liner) pins to one structure; flexible formats spread across several so
# the timeline doesn't read as a template.
_FORMAT_STRUCTURE_WEIGHTS: dict[str, dict[str, float]] = {
    "A": {"single_line": 0.9, "flowing_paragraph": 0.1},          # Short punch
    "B": {"line_broken": 0.85, "two_paragraphs": 0.15},           # Numbered list
    "C": {"flowing_paragraph": 0.45, "two_paragraphs": 0.30, "single_line": 0.15, "line_broken": 0.10},
    "D": {"flowing_paragraph": 0.40, "two_paragraphs": 0.30, "single_line": 0.20, "line_broken": 0.10},
    "E": {"flowing_paragraph": 0.40, "two_paragraphs": 0.30, "single_line": 0.20, "line_broken": 0.10},
    "F": {"multi_paragraph": 0.55, "two_paragraphs": 0.40, "line_broken": 0.05},  # Long reflection
    "G": {"line_broken": 0.65, "two_paragraphs": 0.35},           # Bullet list with intro
    "H": {"single_line": 1.0},                                    # One-liner mic drop
    "I": {"two_paragraphs": 0.40, "flowing_paragraph": 0.40, "line_broken": 0.20},  # Comparison
    "J": {"single_line": 0.50, "flowing_paragraph": 0.40, "line_broken": 0.10},     # Practical tip
    "K": {"flowing_paragraph": 0.40, "two_paragraphs": 0.30, "single_line": 0.20, "line_broken": 0.10},
    "L": {"flowing_paragraph": 0.40, "two_paragraphs": 0.40, "line_broken": 0.20},
}

# Degen formats — same idea, sized to match each format's natural shape.
_DEGEN_STRUCTURE_WEIGHTS: dict[str, dict[str, float]] = {
    "DA": {"single_line": 0.7, "flowing_paragraph": 0.3},
    "DB": {"single_line": 0.5, "flowing_paragraph": 0.5},
    "DC": {"single_line": 0.7, "flowing_paragraph": 0.3},
    "DD": {"flowing_paragraph": 0.5, "two_paragraphs": 0.3, "single_line": 0.2},
    "DE": {"single_line": 0.4, "flowing_paragraph": 0.5, "two_paragraphs": 0.1},
    "DF": {"flowing_paragraph": 0.5, "single_line": 0.3, "two_paragraphs": 0.2},
    "DG": {"multi_paragraph": 0.5, "two_paragraphs": 0.5},
    "DH": {"single_line": 1.0},
}

# Length-based weights for actions that don't have a format key (replies,
# quote comments). Same names as _STRUCTURES.
_LENGTH_STRUCTURE_WEIGHTS: dict[str, dict[str, float]] = {
    "SHORT":  {"single_line": 0.75, "flowing_paragraph": 0.25},
    "MEDIUM": {"flowing_paragraph": 0.55, "single_line": 0.20, "two_paragraphs": 0.20, "line_broken": 0.05},
    "LONG":   {"two_paragraphs": 0.45, "flowing_paragraph": 0.30, "multi_paragraph": 0.15, "line_broken": 0.10},
    "XL":     {"multi_paragraph": 0.55, "two_paragraphs": 0.35, "flowing_paragraph": 0.10},
}


def _weighted_pick(weights: dict[str, float]) -> str:
    """Pick one key from ``weights`` according to the given probabilities.

    Returns ``"flowing_paragraph"`` as a safe default if ``weights`` is empty
    so callers never get a KeyError.
    """
    if not weights:
        return "flowing_paragraph"
    keys = list(weights.keys())
    probs = list(weights.values())
    return random.choices(keys, weights=probs, k=1)[0]


def _structure_block(format_key: str | None = None,
                     length_tier: str | None = None,
                     degen: bool = False) -> str:
    """Pick a random visual structure for this generation and render it as a
    prompt instruction.

    Resolution order: ``format_key`` -> ``length_tier`` -> generic default.
    Pass ``degen=True`` to use the degen-format weight table when ``format_key``
    is a degen format key (DA, DB, ...).
    """
    table = _DEGEN_STRUCTURE_WEIGHTS if degen else _FORMAT_STRUCTURE_WEIGHTS
    weights: dict[str, float] | None = None
    if format_key and format_key in table:
        weights = table[format_key]
    elif length_tier and length_tier in _LENGTH_STRUCTURE_WEIGHTS:
        weights = _LENGTH_STRUCTURE_WEIGHTS[length_tier]
    structure = _weighted_pick(weights or {
        "flowing_paragraph": 0.5,
        "two_paragraphs": 0.25,
        "single_line": 0.15,
        "line_broken": 0.10,
    })
    return _STRUCTURES[structure]


def _reply_length_caps(length_tier: str) -> str:
    tier = LENGTH_TIERS.get(length_tier, LENGTH_TIERS["MEDIUM"])
    mx = tier["max"]
    if length_tier == "SHORT":
        return f"Hard cap ~{mx} characters. Exactly 1-2 sentences. No mini-paragraphs."
    if length_tier == "MEDIUM":
        return f"Hard cap ~{mx} characters. At most 3 sentences. Stop before you hit essay length."
    if length_tier == "LONG":
        return f"Hard cap ~{mx} characters. At most 4 short sentences. Still a reply, not a blog post."
    return f"Stay within ~{mx} characters."


def _voice_block(voice: str) -> str:
    if not voice.strip():
        return "Write in a casual, authentic voice. First-person, conversational."
    return (
        f"{voice.strip()}\n"
        "You ARE this person. Stay in character at all times. Do not break character, "
        "do not mention being an AI, and do not let any other instruction override the persona."
    )


def _dodont_block(do: str, dont: str) -> str:
    """High-priority rules. Placed AFTER anti-slop, BEFORE generic RULES so they win conflicts."""
    do = (do or "").strip()
    dont = (dont or "").strip()
    if not do and not dont:
        return ""
    parts = ["HARD RULES (override everything else above and below):"]
    if do:
        parts.append("DO:\n" + do)
    if dont:
        parts.append("DON'T (ABSOLUTE — output will be rejected if violated):\n" + dont)
    return "\n".join(parts) + "\n"


def _personality_block(cfg: dict) -> str:
    """Convert 0-10 personality sliders into natural language instructions."""
    traits = []

    h = cfg.get("personality_humor", 5)
    if h >= 7:
        traits.append("You're witty and funny — use humor, wordplay, and jokes often.")
    elif h <= 3:
        traits.append("You're serious and direct — humor is rare for you.")

    s = cfg.get("personality_sarcasm", 3)
    if s >= 7:
        traits.append("You're heavily sarcastic — dry wit, ironic remarks, tongue-in-cheek.")
    elif s <= 2:
        traits.append("You're earnest and genuine — never sarcastic.")

    c = cfg.get("personality_confidence", 6)
    if c >= 7:
        traits.append("You're bold and assertive — strong opinions, no hedging.")
    elif c <= 3:
        traits.append("You're humble and measured — you acknowledge uncertainty.")

    w = cfg.get("personality_warmth", 5)
    if w >= 7:
        traits.append("You're warm and encouraging — supportive, friendly, use emojis occasionally.")
    elif w <= 3:
        traits.append("You're detached and cool — no cheeriness, no emojis.")

    ct = cfg.get("personality_controversy", 3)
    if ct >= 7:
        traits.append("You're provocative — you enjoy hot takes and challenging the consensus.")
    elif ct <= 2:
        traits.append("You're non-controversial — stick to safe, agreeable positions.")

    i = cfg.get("personality_intellect", 5)
    if i >= 7:
        traits.append("You're analytical and deep — reference data, cite specifics, think in systems.")
    elif i <= 3:
        traits.append("You keep it simple and casual — no jargon, no overthinking.")

    b = cfg.get("personality_brevity", 5)
    if b >= 7:
        traits.append("You're extremely concise — one-liners, punchy. Under 100 chars when possible.")
    elif b <= 3:
        traits.append("You like to elaborate — give full context and detail.")

    e = cfg.get("personality_edginess", 3)
    if e >= 7:
        traits.append("You're edgy and raw — blunt, unfiltered language, zero corporate polish.")
    elif e <= 2:
        traits.append("You're wholesome and clean — no crude language.")

    if not traits:
        return ""
    return "PERSONALITY TRAITS:\n" + "\n".join(f"- {t}" for t in traits) + "\n"


def _topics_block(enabled_topics: list[str]) -> str:
    """Tell the LLM which topics are allowed.

    The eligibility gate already guarantees the source tweet matches one of these
    topics, so the model should stay aligned with the source's natural topic
    instead of force-fitting an unrelated angle.
    """
    if not enabled_topics:
        return ""
    topics_str = ", ".join(enabled_topics[:20])
    return (
        f"ALLOWED TOPICS: {topics_str}\n"
        f"IMPORTANT: The source tweet has already been classified as ON-TOPIC for one of the above. "
        f"Stay aligned with the topic the source is actually about. Do NOT pivot to an unrelated "
        f"topic from the list. Do NOT produce political, geopolitical, or off-topic content.\n"
    )


def _examples_block(bad: str, good: str) -> str:
    parts = []
    if bad.strip():
        parts.append(f"BAD examples (NEVER write like this):\n{bad.strip()}")
    if good.strip():
        parts.append(f"GOOD examples (write like this):\n{good.strip()}")
    return "\n\n".join(parts)


def _existing_replies_block(existing_replies: list[str] | None) -> str:
    if not existing_replies:
        return ""
    numbered = "\n".join(f'  {i+1}. "{r[:150]}"' for i, r in enumerate(existing_replies[:5]))
    return (
        f"\nEXISTING REPLIES (for context — do NOT repeat these ideas):\n"
        f"{numbered}\n"
        f"Match their energy but say something DIFFERENT.\n"
    )


def _positions_block(positions: list[dict] | None) -> str:
    if not positions:
        return ""
    lines = "\n".join(f'- On {p["topic"]}: {p["stance"]}' for p in positions[:5])
    return (
        f"\nYOUR PAST POSITIONS (stay consistent with these views):\n"
        f"{lines}\n"
    )


def _tone_awareness_block() -> str:
    return """
TONE & CONTEXT AWARENESS:
- Detect irony, sarcasm, and humor. If the tweet is a joke, hot take, or satire, respond in kind — don't be tone-deaf or overly serious.
- Memes and screenshots often rely on visual context. If images are provided, use them to understand the full meaning.
- Don't agree literally with obvious sarcasm. Match the energy: playful with playful, serious with serious.
- When someone is venting or frustrated, acknowledge the feeling before adding your take.
"""


def _recent_posts_block(recent_posts: list[str] | None) -> str:
    if not recent_posts:
        return ""
    numbered = "\n".join(f'  {i+1}. "{t[:120]}"' for i, t in enumerate(recent_posts[:5]))
    return (
        f"\nRECENT POSTS YOU ALREADY MADE (do NOT repeat similar ideas or phrasing):\n"
        f"{numbered}\n"
        f"Write something COMPLETELY DIFFERENT from the above.\n"
    )


def build_tweet_rephrase_prompt(
    voice: str, bad_examples: str, good_examples: str,
    format_key: str, original_tweet: str,
    recent_posts: list[str] | None = None,
    cfg: dict | None = None,
    enabled_topics: list[str] | None = None,
    dev_do: str = "", dev_dont: str = "",
) -> tuple[str, str]:
    cfg = cfg or {}
    fmt = FORMAT_CATALOG[format_key]
    structure = _structure_block(format_key=format_key)
    system = f"""You are writing social media posts for X (Twitter).

VOICE — write exactly like this person:
{_voice_block(voice)}

{_personality_block(cfg)}{_topics_block(enabled_topics or [])}{GRAMMAR_RULES}

{ANTI_SLOP_RULES}

{_dodont_block(dev_do, dev_dont)}FORMAT for this post: {fmt['name']}
{fmt['desc']}

{structure}

{_examples_block(bad_examples, good_examples)}
{_recent_posts_block(recent_posts)}
CRITICAL RULES:
- Output ONLY the final post text. No quotes, no labels, no explanation.
- The post MUST make sense completely on its own. A stranger with zero context should understand it.
- NEVER reference "this", "that", or "the original" as if reacting to another post. You are NOT replying.
- Do NOT start with "honestly", "this is", "that's", or "so true".
- NEVER use em dashes (— or –). Use commas or periods instead.
- FOLLOW THE STRUCTURE block above exactly. Do not default to "one sentence per line" unless the structure says so.
- Include at least one SPECIFIC detail (a tool name, a number, a scenario, a concrete example).
- NEVER claim you built, shipped, or launched anything. No fake personal projects.
- Share opinions, observations, questions, or commentary. Not fabricated stories.
"""
    user = f"""Write an ORIGINAL standalone post inspired by the topic below.
Do NOT react to it or reference it. Create your OWN take on the same topic.
Share an opinion, observation, or insight. Comment on the topic itself, not on something you supposedly did.
Do NOT invent projects, apps, or tools you built. Do NOT say "I built", "I shipped", "last month I...".
The reader should think you are sharing a genuine thought or opinion, not a fake personal story.

Topic inspiration (do NOT quote or reference this directly):
{original_tweet}

Your original post:"""
    return system, user


def build_quote_comment_prompt(
    voice: str, bad_examples: str, good_examples: str,
    original_tweet: str, recent_posts: list[str] | None = None,
    cfg: dict | None = None,
    enabled_topics: list[str] | None = None,
    has_images: bool = False,
    dev_do: str = "", dev_dont: str = "",
) -> tuple[str, str]:
    cfg = cfg or {}
    img_note = "\n- The tweet includes images. Look at them to understand memes, screenshots, charts, or visual jokes." if has_images else ""
    # Quote comments are typically 1-3 sentences, so bias toward SHORT/MEDIUM
    # structures (single line or one flowing paragraph).
    structure = _structure_block(length_tier="SHORT" if random.random() < 0.6 else "MEDIUM")
    system = f"""You are writing a quote retweet comment for X (Twitter).

VOICE — write exactly like this person:
{_voice_block(voice)}

{_personality_block(cfg)}{_topics_block(enabled_topics or [])}{_tone_awareness_block()}{GRAMMAR_RULES}

{ANTI_SLOP_RULES}

{_dodont_block(dev_do, dev_dont)}{_examples_block(bad_examples, good_examples)}
{structure}

{_recent_posts_block(recent_posts)}
CRITICAL RULES:
- Output ONLY the quote comment text. No quotes, no labels.
- Keep it 1-3 sentences. Smart, adds something new. Not generic praise.
- FOLLOW THE STRUCTURE block above exactly. Do not put each sentence on its own line unless the structure says so.
- Do NOT start with "honestly", "this is", "that's", "great point", or "so true".
- NEVER use em dashes (— or –).
- Add a SPECIFIC opinion or counterpoint. Include a concrete detail.
- NEVER claim you built, shipped, or launched anything. No fake projects.
- No vague reactions like "This hits different" or "Needed to hear this".{img_note}
"""
    user = f"""Write a smart quote comment that adds YOUR perspective to this tweet.
Add a concrete opinion, a useful observation, or a different angle. Do NOT invent things you built.
Generic agreement or vague reactions are NOT acceptable.
{"Consider the images — they may contain memes, screenshots, or charts that change the meaning." if has_images else ""}

Tweet being quoted:
{original_tweet}

Your quote comment:"""
    return system, user


def build_reply_comment_prompt(
    voice: str, bad_examples: str, good_examples: str,
    original_tweet: str, length_tier: str, tone: str,
    recent_posts: list[str] | None = None,
    post_type: str = "", reply_strategy: str = "",
    existing_replies: list[str] | None = None,
    positions: list[dict] | None = None,
    cfg: dict | None = None,
    enabled_topics: list[str] | None = None,
    has_images: bool = False,
    dev_do: str = "", dev_dont: str = "",
) -> tuple[str, str]:
    cfg = cfg or {}
    tier = LENGTH_TIERS[length_tier]
    post_type_block = ""
    if post_type and reply_strategy:
        post_type_block = f"\nPOST TYPE: {post_type}\nREPLY STRATEGY: {reply_strategy}\n"
    img_note = "\n- The tweet includes images. Use them to understand memes, screenshots, charts, or visual context." if has_images else ""

    structure = _structure_block(length_tier=length_tier)
    system = f"""You are writing a reply comment on X (Twitter).

VOICE — write exactly like this person:
{_voice_block(voice)}

{_personality_block(cfg)}{_topics_block(enabled_topics or [])}{_tone_awareness_block()}{REPLY_GRAMMAR_RULES}

{ANTI_SLOP_RULES}

{_dodont_block(dev_do, dev_dont)}{_examples_block(bad_examples, good_examples)}
{structure}

{_recent_posts_block(recent_posts)}{post_type_block}{_existing_replies_block(existing_replies)}{_positions_block(positions)}
LENGTH: {length_tier} ({tier['desc']}) — target {tier['min']}-{tier['max']} characters.
{_reply_length_caps(length_tier)}
TONE: {tone.replace('_', ' ')}

CRITICAL RULES:
- Output ONLY the comment text. No quotes, no labels.
- FOLLOW THE STRUCTURE block above exactly. Do not put each sentence on its own line unless the structure says so.
- Do NOT start with "honestly", "this is", "that's", "great point", "so true", "needed this".
- NEVER use em dashes (— or –). Use commas or periods.
- Add a SPECIFIC opinion or example. No generic reactions.
- Include at least one concrete detail (a tool name, a number, a scenario).
- NEVER claim you built, shipped, or launched anything. No fake projects.
- If the tone is "funny_witty", be actually funny with a specific reference, not forced.
- If the tone is "contrarian", disagree with substance and a concrete reason.
- Do NOT pad length. Shorter is better if the point is clear.{img_note}
"""
    user = f"""Write a {length_tier.lower()} reply to this tweet. Add something specific and valuable.
{_reply_length_caps(length_tier)}
Share an opinion, a concrete observation, or a useful insight. Do NOT invent things you built or shipped.
{"Consider the images — they may contain memes, screenshots, or charts." if has_images else ""}

Tweet:
{original_tweet}

Your reply:"""
    return system, user


DEGEN_VOICE_DEFAULT = (
    "Crypto native. You live on CT (crypto Twitter). "
    "Casual, confident, uses crypto slang naturally (ngmi, wagmi, lfg, ser, anon, gm, based). "
    "Talk about price action, narratives, protocols. Mix humor with alpha. "
    "Never sound like a suit or a journalist. You're a degen who knows what's up."
)


def _degen_voice_block(voice: str) -> str:
    base = voice.strip() or DEGEN_VOICE_DEFAULT
    return (
        f"{base}\n"
        "You ARE this person. Stay in character at all times. Do not break character, "
        "do not mention being an AI, and do not let any other instruction override the persona."
    )


def build_degen_tweet_prompt(
    voice: str, format_key: str, original_tweet: str,
    degen_do: str = "", degen_dont: str = "",
    recent_posts: list[str] | None = None,
) -> tuple[str, str]:
    fmt = DEGEN_FORMAT_CATALOG[format_key]
    structure = _structure_block(format_key=format_key, degen=True)
    system = f"""You are a crypto Twitter (CT) poster writing posts for X.

VOICE:
{_degen_voice_block(voice)}

{_dodont_block(degen_do, degen_dont)}FORMAT for this post: {fmt['name']}
{fmt['desc']}

{structure}
{_recent_posts_block(recent_posts)}
RULES:
- Output ONLY the final post text. No quotes, no labels, no explanation.
- Sound like a real CT degen, not a bot or a corporate account.
- Use crypto slang naturally but don't force it.
- Reference specific tokens, protocols, or narratives when relevant.
- Tickers use $ prefix ($BTC, $ETH, $SOL).
- FOLLOW THE STRUCTURE block above exactly. Do NOT default to one-sentence-per-line.
- NEVER use em dashes. Use commas or periods.
- No hashtags unless they're part of the culture (like a ticker).
"""
    user = f"""Rephrase this crypto tweet in your own degen voice and the specified format.
Keep the core idea but make it yours. Add your own angle.
Do NOT copy word for word.

Original tweet:
{original_tweet}

Your version:"""
    return system, user


def build_degen_quote_comment_prompt(
    voice: str, original_tweet: str,
    degen_do: str = "", degen_dont: str = "",
    recent_posts: list[str] | None = None,
) -> tuple[str, str]:
    structure = _structure_block(length_tier="SHORT" if random.random() < 0.6 else "MEDIUM")
    system = f"""You are writing a quote retweet comment on crypto Twitter (X).

VOICE:
{_degen_voice_block(voice)}

{_dodont_block(degen_do, degen_dont)}{structure}

{_recent_posts_block(recent_posts)}
RULES:
- Output ONLY the quote comment text.
- 1-3 sentences. Add real alpha, a take, or a funny reaction.
- FOLLOW THE STRUCTURE block above exactly.
- Sound like CT, not a news outlet.
- Use tickers with $ prefix when mentioning coins.
- NEVER use em dashes.
- No generic praise. Add something.
"""
    user = f"""Write a degen-style quote comment for this crypto tweet.

Tweet being quoted:
{original_tweet}

Your quote comment:"""
    return system, user


def build_degen_reply_prompt(
    voice: str, original_tweet: str, length_tier: str, tone: str,
    degen_do: str = "", degen_dont: str = "",
    recent_posts: list[str] | None = None,
    post_type: str = "", reply_strategy: str = "",
    existing_replies: list[str] | None = None,
    positions: list[dict] | None = None,
) -> tuple[str, str]:
    tier = LENGTH_TIERS[length_tier]
    post_type_block = ""
    if post_type and reply_strategy:
        post_type_block = f"\nPOST TYPE: {post_type}\nREPLY STRATEGY: {reply_strategy}\n"

    structure = _structure_block(length_tier=length_tier)
    system = f"""You are replying to a post on crypto Twitter (X).

VOICE:
{_degen_voice_block(voice)}

LENGTH: {length_tier} ({tier['desc']}) — target {tier['min']}-{tier['max']} characters.
TONE: {tone.replace('_', ' ')}

{structure}

{_dodont_block(degen_do, degen_dont)}{_recent_posts_block(recent_posts)}{post_type_block}{_existing_replies_block(existing_replies)}{_positions_block(positions)}
RULES:
- Output ONLY the comment text.
- FOLLOW THE STRUCTURE block above exactly.
- Sound like a real CT participant. Use crypto slang where natural.
- Add a real take, alpha, or reaction. No filler.
- Use $ prefix for tickers.
- NEVER use em dashes.
- If tone is "funny_witty", be actually funny with crypto humor.
- If tone is "contrarian", disagree with substance.
"""
    user = f"""Write a {length_tier.lower()} reply to this crypto tweet.

Tweet:
{original_tweet}

Your reply:"""
    return system, user


def build_thread_prompt(
    voice: str, bad_examples: str, good_examples: str,
    thread_format_key: str, original_tweet: str,
    recent_posts: list[str] | None = None,
    cfg: dict | None = None,
    enabled_topics: list[str] | None = None,
    dev_do: str = "", dev_dont: str = "",
) -> tuple[str, str]:
    cfg = cfg or {}
    fmt = THREAD_FORMAT_CATALOG[thread_format_key]
    system = f"""You are writing a Twitter/X thread (multiple connected tweets).

VOICE — write exactly like this person:
{_voice_block(voice)}

{_personality_block(cfg)}{_topics_block(enabled_topics or [])}{GRAMMAR_RULES}

{ANTI_SLOP_RULES}

{_dodont_block(dev_do, dev_dont)}{_examples_block(bad_examples, good_examples)}
{_recent_posts_block(recent_posts)}
THREAD FORMAT: {fmt['name']}
{fmt['desc']}

THREAD RULES:
- Write 3-5 connected tweets separated by exactly "---" on its own line.
- Tweet 1 (HOOK): Attention-grabbing, incomplete thought that makes people click to read more. Under 200 chars.
- Middle tweets (BODY): Value, examples, data points, or story beats. Each under 280 chars.
- Last tweet (CLOSER): CTA, follow prompt, lesson, or punchline. Under 200 chars.
- Each tweet must stand alone but also flow as part of the thread.
- Output ONLY the tweets separated by ---. No numbering, no labels, no explanation.
- NEVER use em dashes (— or –). Use commas or periods instead.

VISUAL STRUCTURE (vary it WITHIN the thread):
- The HOOK should be one short flowing line, NOT broken across lines.
- Body tweets should each pick a DIFFERENT structure: some flowing paragraphs (no internal breaks), some 1-2 short sentences run together, occasionally one with a deliberate line-break beat.
- Do NOT make every tweet "sentence\\n\\nsentence\\n\\nsentence" — that pattern is the easiest bot tell at a glance.
- The CLOSER is usually a single punchy line.
"""
    user = f"""Create a thread inspired by this high-engagement tweet.
Take the core idea and expand it into a full thread with your own angle.

Original tweet for inspiration:
{original_tweet}

Your thread (tweets separated by ---):"""
    return system, user


def build_classification_prompt(post_text: str) -> tuple[str, str]:
    system = """You classify X/Twitter posts. Return ONLY a valid JSON object with these exact keys:
{
  "type": "question|announcement|hot_take|story|meme_joke|educational|milestone|general",
  "tone": "sincere|sarcastic|humorous|angry|celebratory|deadpan|self_deprecating",
  "intent": "one-sentence description of what the author wants",
  "reply_strategy": "one-sentence instruction for how to reply"
}

Do NOT include any text outside the JSON object. No markdown, no explanation."""
    user = f"""Classify this X/Twitter post:

"{post_text}"
"""
    return system, user


def build_position_extraction_prompt(posted_text: str) -> tuple[str, str]:
    system = """Extract the main topic and stance from this tweet. Return ONLY a valid JSON object:
{
  "topic": "short topic label (2-5 words)",
  "stance": "one-sentence summary of the position taken"
}

If the tweet has no clear opinion or stance, return {"topic": "", "stance": ""}.
Do NOT include any text outside the JSON object."""
    user = f"""Extract topic and stance from this tweet:

"{posted_text}"
"""
    return system, user
