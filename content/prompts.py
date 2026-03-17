"""Dynamic system prompt builder. Injects user voice + built-in rules."""

from content.rules import (
    GRAMMAR_RULES,
    ANTI_SLOP_RULES,
    FORMAT_CATALOG,
    DEGEN_FORMAT_CATALOG,
    LENGTH_TIERS,
    THREAD_FORMAT_CATALOG,
)


def _voice_block(voice: str) -> str:
    if not voice.strip():
        return "Write in a casual, authentic voice. First-person, conversational."
    return voice.strip()


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
    voice: str,
    bad_examples: str,
    good_examples: str,
    format_key: str,
    original_tweet: str,
    recent_posts: list[str] | None = None,
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for rephrasing a stolen tweet."""
    fmt = FORMAT_CATALOG[format_key]
    system = f"""You are writing social media posts for X (Twitter).

VOICE — write exactly like this person:
{_voice_block(voice)}

{GRAMMAR_RULES}

{ANTI_SLOP_RULES}

FORMAT for this post: {fmt['name']}
{fmt['desc']}

{_examples_block(bad_examples, good_examples)}
{_recent_posts_block(recent_posts)}
CRITICAL RULES:
- Output ONLY the final post text. No quotes, no labels, no explanation.
- Do NOT start with "honestly" or "this is".
- NEVER use em dashes (— or –). Use commas or periods instead.
- Use line breaks between sentences (each sentence on its own line with a blank line gap).
"""

    user = f"""Rephrase this high-engagement tweet in your own voice and the specified format.
Keep the core idea but make it yours. Add your own angle or detail.
Do NOT copy it word for word. Change the structure, wording, and add personality.

Original tweet:
{original_tweet}

Your rephrased version:"""

    return system, user


def build_quote_comment_prompt(
    voice: str,
    bad_examples: str,
    good_examples: str,
    original_tweet: str,
    recent_posts: list[str] | None = None,
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for a quote RT comment."""
    system = f"""You are writing a quote retweet comment for X (Twitter).

VOICE — write exactly like this person:
{_voice_block(voice)}

{GRAMMAR_RULES}

{ANTI_SLOP_RULES}

{_examples_block(bad_examples, good_examples)}
{_recent_posts_block(recent_posts)}
CRITICAL RULES:
- Output ONLY the quote comment text. No quotes, no labels.
- Keep it 1-3 sentences. Smart, adds something new. Not generic praise.
- Do NOT start with "honestly" or "this is" or "great point".
- NEVER use em dashes (— or –).
- Add a real opinion, observation, or experience. No filler.
"""

    user = f"""Write a smart, meaningful quote comment for this tweet.
Your comment should add perspective, not just agree.

Tweet being quoted:
{original_tweet}

Your quote comment:"""

    return system, user


def build_reply_comment_prompt(
    voice: str,
    bad_examples: str,
    good_examples: str,
    original_tweet: str,
    length_tier: str,
    tone: str,
    recent_posts: list[str] | None = None,
    post_type: str = "",
    reply_strategy: str = "",
    existing_replies: list[str] | None = None,
    positions: list[dict] | None = None,
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for a reply comment."""
    tier = LENGTH_TIERS[length_tier]
    post_type_block = ""
    if post_type and reply_strategy:
        post_type_block = f"\nPOST TYPE: {post_type}\nREPLY STRATEGY: {reply_strategy}\n"

    system = f"""You are writing a reply comment on X (Twitter).

VOICE — write exactly like this person:
{_voice_block(voice)}

{GRAMMAR_RULES}

{ANTI_SLOP_RULES}

{_examples_block(bad_examples, good_examples)}
{_recent_posts_block(recent_posts)}{post_type_block}{_existing_replies_block(existing_replies)}{_positions_block(positions)}
LENGTH: {length_tier} ({tier['desc']}) — target {tier['min']}-{tier['max']} characters.
TONE: {tone.replace('_', ' ')}

CRITICAL RULES:
- Output ONLY the comment text. No quotes, no labels.
- Do NOT start with "honestly" or "this is" or "great point" or "so true".
- NEVER use em dashes (— or –). Use commas or periods.
- Add a real opinion, new angle, or personal experience. No generic agreement.
- If the tone is "funny_witty", be actually funny, not forced.
- If the tone is "contrarian", disagree with substance, not just to disagree.
- Use line breaks between sentences for MEDIUM and LONG comments.
"""

    user = f"""Write a {length_tier.lower()} reply comment to this tweet.

Tweet:
{original_tweet}

Your reply:"""

    return system, user


# --- Project Farming prompts ---

def build_project_reply_prompt(
    post_text: str,
    post_author: str,
    top_replies: list[str],
    project_name: str,
    project_about: str = "",
    project_do: str = "",
    project_dont: str = "",
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for a context-aware reply-guy comment."""
    replies_block = ""
    if top_replies:
        numbered = "\n".join(f"  {i+1}. {r}" for i, r in enumerate(top_replies))
        replies_block = f"\nTop replies from other users:\n{numbered}\n"

    identity_block = ""
    if project_name:
        identity_block += f"\nYOUR PROJECT: {project_name}"
    if project_about:
        identity_block += f"\nABOUT YOU: {project_about}"
    if identity_block:
        identity_block += (
            "\n- You can subtly reference what your project does when it's relevant, "
            "but NEVER shill or self-promote. You're a community member first."
            "\n- Use your project name in casual greetings when it fits (e.g. 'g{name}', 'gm from {name}')."
        ).format(name=project_name)
        identity_block += "\n"

    custom_rules = ""
    if project_do:
        custom_rules += f"\nDO:\n{project_do}\n"
    if project_dont:
        custom_rules += f"\nDON'T:\n{project_dont}\n"

    system = f"""You are a crypto Twitter "reply guy". Your ONLY job is to drop short, positive engagement comments that match the vibe of the post and its replies.
{identity_block}{custom_rules}
PERSONALITY:
- You are a supportive community member, always positive.
- You read the room. If people are joking, you joke along. If people are hyped, you hype.
- If the post is sarcastic or ironic, you match that energy.
- If everyone is replying with the same phrase or meme (like "touch grass"), you do the same.
- You never give opinions on price, competitors, regulation, or anything controversial.
- You never say anything offensive, negative, or argumentative.

OUTPUT RULES:
- Output ONLY the reply text. Nothing else. No quotes, no labels, no explanation.
- Keep it SHORT. 1-8 words is ideal. Max 15 words.
- All lowercase is fine. Abbreviations are fine. Crypto slang is fine.
- Match the energy and format of the existing replies.
- If the post is a meme or joke, react to the humor. Don't explain it.
- If the post is an announcement, be hyped.
- If the post says something like "touch grass" or any catchphrase, echo it or riff on it.
- NEVER use em dashes, hashtags, or formal language.

BANNED — never include any of these:
- Price predictions, financial advice, tickers ($XXX)
- Negative words: scam, rug, dead, dump, sell, hate, trash
- Controversial opinions on anything
- Competitor comparisons
- Anything longer than 2 sentences"""

    user = f"""Post by @{post_author}:
"{post_text}"
{replies_block}
Write a short reply-guy comment that fits this post's vibe. Match what others are replying if a pattern is clear.

Your reply:"""

    return system, user


# --- Degen Farming prompts ---

DEGEN_VOICE_DEFAULT = (
    "Crypto native. You live on CT (crypto Twitter). "
    "Casual, confident, uses crypto slang naturally (ngmi, wagmi, lfg, ser, anon, gm, based). "
    "Talk about price action, narratives, protocols. Mix humor with alpha. "
    "Never sound like a suit or a journalist. You're a degen who knows what's up."
)


def _degen_voice_block(voice: str) -> str:
    if not voice.strip():
        return DEGEN_VOICE_DEFAULT
    return voice.strip()


def build_degen_tweet_prompt(
    voice: str,
    format_key: str,
    original_tweet: str,
    degen_do: str = "",
    degen_dont: str = "",
    recent_posts: list[str] | None = None,
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for a degen-style rephrased tweet."""
    fmt = DEGEN_FORMAT_CATALOG[format_key]
    custom_rules = ""
    if degen_do:
        custom_rules += f"\nDO:\n{degen_do}\n"
    if degen_dont:
        custom_rules += f"\nDON'T:\n{degen_dont}\n"

    system = f"""You are a crypto Twitter (CT) poster writing posts for X.

VOICE:
{_degen_voice_block(voice)}

FORMAT for this post: {fmt['name']}
{fmt['desc']}
{custom_rules}{_recent_posts_block(recent_posts)}
RULES:
- Output ONLY the final post text. No quotes, no labels, no explanation.
- Sound like a real CT degen, not a bot or a corporate account.
- Use crypto slang naturally but don't force it.
- Reference specific tokens, protocols, or narratives when relevant.
- Tickers use $ prefix ($BTC, $ETH, $SOL).
- Keep line breaks between sentences.
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
    voice: str,
    original_tweet: str,
    degen_do: str = "",
    degen_dont: str = "",
    recent_posts: list[str] | None = None,
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for a degen quote RT comment."""
    custom_rules = ""
    if degen_do:
        custom_rules += f"\nDO:\n{degen_do}\n"
    if degen_dont:
        custom_rules += f"\nDON'T:\n{degen_dont}\n"

    system = f"""You are writing a quote retweet comment on crypto Twitter (X).

VOICE:
{_degen_voice_block(voice)}
{custom_rules}{_recent_posts_block(recent_posts)}
RULES:
- Output ONLY the quote comment text.
- 1-3 sentences. Add real alpha, a take, or a funny reaction.
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
    voice: str,
    original_tweet: str,
    length_tier: str,
    tone: str,
    degen_do: str = "",
    degen_dont: str = "",
    recent_posts: list[str] | None = None,
    post_type: str = "",
    reply_strategy: str = "",
    existing_replies: list[str] | None = None,
    positions: list[dict] | None = None,
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for a degen reply comment."""
    tier = LENGTH_TIERS[length_tier]
    custom_rules = ""
    if degen_do:
        custom_rules += f"\nDO:\n{degen_do}\n"
    if degen_dont:
        custom_rules += f"\nDON'T:\n{degen_dont}\n"

    post_type_block = ""
    if post_type and reply_strategy:
        post_type_block = f"\nPOST TYPE: {post_type}\nREPLY STRATEGY: {reply_strategy}\n"

    system = f"""You are replying to a post on crypto Twitter (X).

VOICE:
{_degen_voice_block(voice)}

LENGTH: {length_tier} ({tier['desc']}) — target {tier['min']}-{tier['max']} characters.
TONE: {tone.replace('_', ' ')}
{custom_rules}{_recent_posts_block(recent_posts)}{post_type_block}{_existing_replies_block(existing_replies)}{_positions_block(positions)}
RULES:
- Output ONLY the comment text.
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


# --- Thread prompts ---

def build_thread_prompt(
    voice: str,
    bad_examples: str,
    good_examples: str,
    thread_format_key: str,
    original_tweet: str,
    recent_posts: list[str] | None = None,
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for generating a multi-tweet thread."""
    fmt = THREAD_FORMAT_CATALOG[thread_format_key]
    system = f"""You are writing a Twitter/X thread (multiple connected tweets).

VOICE — write exactly like this person:
{_voice_block(voice)}

{GRAMMAR_RULES}

{ANTI_SLOP_RULES}

{_examples_block(bad_examples, good_examples)}
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
"""

    user = f"""Create a thread inspired by this high-engagement tweet.
Take the core idea and expand it into a full thread with your own angle.

Original tweet for inspiration:
{original_tweet}

Your thread (tweets separated by ---):"""

    return system, user


# --- Classification prompts ---

def build_classification_prompt(post_text: str) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for LLM-based post classification."""
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
    """Returns (system_prompt, user_prompt) for extracting topic/stance from a posted tweet."""
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
