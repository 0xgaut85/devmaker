"""Built-in content rules: grammar, anti-slop, formats, lengths, tones."""

GRAMMAR_RULES = """
GRAMMAR (non-negotiable):
- Start every sentence with a capital letter. Capitalize "I", names, proper nouns.
- Use commas at natural pauses and in lists. No Oxford comma.
- NEVER use em dashes (— or –). Use commas, periods, or line breaks instead.
- End sentences with a period (or ? / ! when appropriate).
- Connect related ideas with commas or new sentences. No "sentence. lowercase sentence." pattern.

VISUAL STRUCTURE (vary it — readers spot bots by scrolling):
- Do NOT default to "one sentence, blank line, one sentence, blank line". That layout is the single biggest tell.
- Match the STRUCTURE block below for THIS post. If it says "single flowing paragraph", do NOT break sentences onto separate lines. If it says "two paragraphs with a gap", use ONE blank line between two coherent paragraphs (each paragraph = several sentences flowing together, not one per line).
- Line breaks are a deliberate beat, not a default rhythm. Use them when they ADD meaning, not as a uniform separator.
""".strip()

REPLY_GRAMMAR_RULES = """
REPLY FORMATTING (replies only — keep compact):
- Start sentences with capitals. NEVER use em dashes (— or –).
- SHORT: one paragraph, at most 2 sentences, no blank lines between sentences.
- MEDIUM: at most 3 sentences; single paragraph or one line break if truly needed.
- LONG: at most 4 short sentences; do not write an essay or multiple blank-line paragraphs.
"""

ANTI_SLOP_RULES = """
ANTI-SLOP (non-negotiable):
- No generic agreement ("This is so true", "Great point about X").
- No vague wisdom ("The real lesson here is to always keep learning").
- No filler observations ("This is genuinely one of the best pieces of advice").
- No obvious restatement of what the original post said.
- Every post MUST add NEW information, perspective, or a real opinion.
- Be SPECIFIC: include one concrete detail, number, or example per post.
- Have a real opinion. "Both have pros and cons" is banned.
- Vary sentence length. Mix short punchy lines with longer ones.
- Allow incomplete thoughts. "Still not sure if this scales. But for our case it worked." is fine.
- No corporate voice. Never use: "leverage", "utilize", "ensure", "stakeholders", "align".
- No "here are 3 ways" unless you genuinely have 3 real points. Padding shows.

ANTI-FABRICATION (critical):
- NEVER claim you built, shipped, created, or launched something unless the voice description says you did.
- NEVER say "I built", "I shipped", "last month I built", "we launched", "I created", "I made".
- NEVER invent fake personal projects, apps, tools, or startups.
- Instead of fake first-person stories, share OBSERVATIONS, OPINIONS, QUESTIONS, or REACTIONS.
- Good: "Postgres handles this way better than people think." Bad: "I built a tool last week that..."
- Good: "The real bottleneck in most apps is the ORM layer." Bad: "When I shipped my app..."
- You can reference general experience ("I've seen this pattern", "In my experience") but NEVER invent specific projects.
- Comment on the TOPIC, not on fake things you supposedly did.
""".strip()

# Hard-coded slop list — kept intentionally TIGHT.
# Users now control content via dev_do/dev_dont; the only entries here are
# universally agreed LLM tells that no one writes naturally on X. We removed
# first-person fabrication phrases ("i built", "i shipped"…) because
# (a) the ANTI_FABRICATION prompt block already steers the LLM, and
# (b) banning them outright contradicts personas where the user IS a dev who
#     legitimately ships things, which caused infinite retry loops.
BANNED_PHRASES = [
    "game-changer",
    "dive deep",
    "let's be real",
    "at the end of the day",
    "underrated gem",
    "can't recommend enough",
]

BANNED_OPENERS = [
    "honestly,",
    "honestly ",
    "this is so ",
    "this is genuinely ",
    "this is truly ",
    "this is the best ",
    "this is the most ",
    "great point,",
    "great point ",
    "so true,",
    "so true ",
    "so true.",
    "couldn't agree more",
    "this right here",
]

FORMAT_CATALOG = {
    "A": {"name": "Short punch", "desc": "1-2 sentences, <80 chars. Punchy one-liner."},
    "B": {"name": "Numbered list", "desc": "3 things worth knowing about this topic. Use \\n\\n between items."},
    "C": {"name": "Observation", "desc": "A sharp observation about a trend or pattern. ~200 chars with setup + insight."},
    "D": {"name": "Question hook", "desc": "Start with a provocative question, then give your take."},
    "E": {"name": "Contrarian opener", "desc": "Lead with a counter-consensus opinion (do NOT literally write 'Hot take:' as the opener), then back it up with one or two specifics."},
    "F": {"name": "Long reflection", "desc": "400+ chars, 3-4 distinct paragraphs. Deep thinking about the topic."},
    "G": {"name": "Bullet list with intro", "desc": "Intro sentence, then bullet points with \\n\\n- format."},
    "H": {"name": "One-liner mic drop", "desc": "Single devastating sentence. That's it."},
    "I": {"name": "Comparison / X vs Y", "desc": "Compare two tools, approaches, or ideas. Why one wins over the other."},
    "J": {"name": "Practical tip", "desc": "A useful tip about a tool or workflow. Quick and actionable."},
    "K": {"name": "Hot take on a tool", "desc": "An opinion about a popular tool. What's overrated, underrated, or misunderstood."},
    "L": {"name": "Industry pattern", "desc": "A pattern you've noticed in the industry. What's changing and why it matters."},
}

FORMAT_ORDER = list(FORMAT_CATALOG.keys())

# Each tweet format has a natural length. Coupling them here prevents the
# orchestrator from generating, e.g., a "long reflection" with a SHORT cap or a
# one-liner mic drop with a LONG cap.
LENGTH_FOR_FORMAT: dict[str, str] = {
    "A": "SHORT",   # Short punch
    "B": "MEDIUM",  # Numbered list
    "C": "MEDIUM",  # Observation
    "D": "MEDIUM",  # Question hook
    "E": "MEDIUM",  # Contrarian opener
    "F": "LONG",    # Long reflection
    "G": "LONG",    # Bullet list with intro
    "H": "SHORT",   # One-liner mic drop
    "I": "MEDIUM",  # Comparison
    "J": "SHORT",   # Practical tip
    "K": "MEDIUM",  # Hot take on a tool
    "L": "MEDIUM",  # Industry pattern
}

DEGEN_FORMAT_CATALOG = {
    "DA": {"name": "CT hot take", "desc": "1-2 sentences. Spicy crypto Twitter opinion. Confident tone."},
    "DB": {"name": "Market call", "desc": "Short price/market take. Reference a coin or trend. Bold conviction."},
    "DC": {"name": "Meme reaction", "desc": "React to something happening in crypto. Short, funny, relatable."},
    "DD": {"name": "Alpha drop", "desc": "Share a tip or observation about a protocol, token, or narrative."},
    "DE": {"name": "Ticker shill", "desc": "Mention a ticker ($XXX). Say why you're bullish. 1-3 sentences."},
    "DF": {"name": "Chart commentary", "desc": "Comment on price action or chart pattern. Use trader lingo."},
    "DG": {"name": "Thread starter", "desc": "Open a topic with a hook. 3-4 short paragraphs about a crypto thesis."},
    "DH": {"name": "Ratio bait", "desc": "Provocative one-liner designed to spark engagement. Confident, edgy."},
}

DEGEN_FORMAT_ORDER = list(DEGEN_FORMAT_CATALOG.keys())

DEGEN_TOPIC_KEYWORDS = {
    "BTC / Bitcoin": ["btc", "bitcoin", "sats", "halving", "satoshi", "digital gold", "store of value"],
    "ETH / Ethereum": ["eth", "ethereum", "vitalik", "eip", "the merge", "staking", "beacon"],
    "Solana / SOL": ["solana", "sol", "$sol", "solana phone", "jito", "marinade", "raydium", "jupiter"],
    "Meme coins": ["meme coin", "memecoin", "doge", "shib", "pepe", "bonk", "wif", "floki", "pump.fun", "rug"],
    "DeFi": ["defi", "dex", "amm", "yield", "tvl", "liquidity", "uniswap", "aave", "compound", "lending"],
    "NFTs": ["nft", "pfp", "mint", "collection", "floor price", "opensea", "blur", "ordinals", "inscription"],
    "Market analysis": ["market", "bull", "bear", "cycle", "macro", "rally", "dump", "pump", "correction", "ath"],
    "Airdrops / Farming": ["airdrop", "farming", "points", "testnet", "incentive", "claim", "eligibility", "season"],
    "Layer 2s": ["layer 2", "l2", "rollup", "arbitrum", "optimism", "base", "zksync", "starknet", "scroll"],
    "Crypto news": ["breaking", "announced", "launch", "partnership", "listing", "sec", "etf", "regulation"],
    "Trading / Charts": ["chart", "candle", "rsi", "macd", "support", "resistance", "breakout", "long", "short", "leverage"],
    "Regulation / Policy": ["regulation", "sec", "gensler", "congress", "ban", "compliance", "kyc", "cbdc"],
}

LENGTH_TIERS = {
    "SHORT": {"min": 1, "max": 100, "desc": "1-2 sentences, punchy"},
    "MEDIUM": {"min": 100, "max": 250, "desc": "3-4 sentences, adds substance"},
    "LONG": {"min": 250, "max": 500, "desc": "Paragraph with line breaks, deep engagement"},
    "XL": {"min": 500, "max": 2000, "desc": "Long tweet, multiple paragraphs"},
}

COMMENT_ROTATIONS = [
    ["SHORT", "SHORT", "MEDIUM", "SHORT", "SHORT"],
    ["SHORT", "MEDIUM", "SHORT", "SHORT", "SHORT"],
    ["SHORT", "SHORT", "SHORT", "MEDIUM", "SHORT"],
    ["MEDIUM", "SHORT", "SHORT", "SHORT", "MEDIUM"],
    ["SHORT", "SHORT", "SHORT", "SHORT", "MEDIUM"],
    ["SHORT", "SHORT", "MEDIUM", "SHORT", "MEDIUM"],
    ["SHORT", "MEDIUM", "SHORT", "SHORT", "LONG"],
    ["SHORT", "SHORT", "SHORT", "SHORT", "SHORT"],
]

TONE_TARGETS = {
    "sharp_opinionated": 0.30,
    "helpful": 0.25,
    "funny_witty": 0.20,
    "contrarian": 0.15,
    "supportive": 0.10,
}

TONE_LIST = list(TONE_TARGETS.keys())

POST_TYPES = {
    "question": {
        "signals": ["?", "what do you", "how do you", "thoughts on", "which one", "anyone know", "what's your", "how would you"],
        "strategy": "Answer concretely. Share your specific experience or opinion. Don't dodge the question.",
    },
    "announcement": {
        "signals": ["just launched", "shipped", "releasing", "announcing", "excited to", "now live", "introducing", "we're thrilled", "big news"],
        "strategy": "React with enthusiasm. Ask a smart follow-up question about specifics or use case.",
    },
    "hot_take": {
        "signals": ["hot take", "unpopular opinion", "controversial", "i think", "people don't realize", "nobody talks about", "most people"],
        "strategy": "Engage the take. Add a supporting example OR a thoughtful counter-argument. Have a real stance.",
    },
    "story": {
        "signals": ["last week", "yesterday", "just happened", "story time", "i was", "we were", "3 months ago", "learned the hard way"],
        "strategy": "Relate to the story. Ask a follow-up question or share a relevant observation. Do NOT invent your own story.",
    },
    "meme_joke": {
        "signals": ["lmao", "lol", "bruh", "no way", "ratio", "touch grass", "real ones know", "pov:", "me when"],
        "strategy": "Match the humor energy. Riff on the joke. Keep it short and punchy. Don't explain the joke.",
    },
    "educational": {
        "signals": ["thread", "here's how", "step 1", "tutorial", "guide", "til", "did you know", "pro tip", "how to"],
        "strategy": "Add a practical tip the author missed. Or mention a related tool or approach worth exploring.",
    },
    "milestone": {
        "signals": ["reached", "hit", "crossed", "milestone", "users", "revenue", "raised", "grew to", "from 0 to"],
        "strategy": "Celebrate genuinely. Ask about the journey, the hardest part, or what's next.",
    },
}


def classify_post_type(text: str) -> tuple[str, str]:
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for ptype, info in POST_TYPES.items():
        score = sum(1 for sig in info["signals"] if sig in text_lower)
        if score > 0:
            scores[ptype] = score
    if scores:
        best = max(scores, key=scores.get)
        return best, POST_TYPES[best]["strategy"]
    return "general", "Add a real opinion, new angle, or concrete observation. Be specific."


THREAD_FORMAT_CATALOG = {
    "T1": {"name": "Value thread", "desc": "3-5 tweets sharing practical knowledge. Hook tweet + value + CTA."},
    "T2": {"name": "Hot take thread", "desc": "3-4 tweets. Bold opening claim, supporting arguments, conclusion."},
    "T3": {"name": "Insight thread", "desc": "4-6 tweets. A trend or pattern explained. Setup, evidence, takeaway."},
}

THREAD_FORMAT_ORDER = list(THREAD_FORMAT_CATALOG.keys())
