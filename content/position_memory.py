"""Position memory — track and retrieve opinion consistency across sessions."""


_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "and",
    "in", "that", "it", "for", "on", "with", "as", "at", "by", "this", "i",
    "my", "me", "we", "you", "do", "so", "if", "or", "but", "not", "no",
    "just", "like", "really", "very", "all", "can", "will", "about", "been",
    "have", "has", "had", "would", "could", "should", "from", "they",
})


def _keywords(text: str) -> set[str]:
    return {w for w in text.lower().split() if w not in _STOPWORDS and len(w) > 2}


def record_position(state, topic: str, stance: str, timestamp: str = ""):
    """Record a stance on a topic. Caps history at 30 entries."""
    entry = {"topic": topic, "stance": stance}
    if timestamp:
        entry["posted_at"] = timestamp
    state.position_history.append(entry)
    state.position_history = state.position_history[-30:]


def get_relevant_positions(state, post_text: str, n: int = 3) -> list[dict]:
    """Return up to n positions relevant to the given post text via keyword overlap."""
    if not state.position_history:
        return []
    post_kw = _keywords(post_text)
    if not post_kw:
        return []

    scored = []
    for pos in state.position_history:
        topic_kw = _keywords(pos.get("topic", ""))
        stance_kw = _keywords(pos.get("stance", ""))
        combined = topic_kw | stance_kw
        overlap = len(post_kw & combined)
        if overlap > 0:
            scored.append((overlap, pos))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [pos for _, pos in scored[:n]]
