"""Topic keywords and classification — single place for dev-mode topic matching."""

from __future__ import annotations

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "Database / backend": ["postgres", "sql", "database", "redis", "backend", "migration", "orm", "prisma", "supabase", "mongodb"],
    "Frontend / UI / UX": ["frontend", "react", "css", "tailwind", "ui", "ux", "design system", "component", "nextjs", "next.js", "svelte", "vue"],
    "DevOps / infra": ["deploy", "ci/cd", "docker", "kubernetes", "k8s", "terraform", "aws", "gcp", "azure", "infra", "monitoring"],
    "AI / ML tools": ["gpt", "claude", "llm", "openai", "copilot", "cursor", "ai coding", "model", "fine-tun", "benchmark"],
    "Open source": ["open source", "open-source", "oss", "github", "contributor", "maintainer", "license", "fork"],
    "Startup / founder life": ["startup", "founder", "fundrais", "pivot", "pmf", "product-market", "launch", "yc", "investor", "seed", "series"],
    "Career / growth": ["hiring", "interview", "promotion", "resume", "career", "mentor", "salary", "job"],
    "Developer tools / productivity": ["ide", "vscode", "terminal", "cli", "neovim", "vim", "workflow", "dev tools", "productivity"],
    "Product thinking": ["feature", "roadmap", "user research", "ship", "prioriti", "product"],
    "Hardware / gadgets": ["hardware", "gadget", "device", "peripheral", "monitor", "keyboard", "mouse", "home office"],
    "Remote work / async": ["remote", "async", "timezone", "wfh", "hybrid", "distributed"],
    "Side projects": ["side project", "build in public", "indie", "solo", "weekend project", "burnout", "scope creep"],
    "Security / privacy": ["security", "auth", "encrypt", "vulnerability", "pentest", "oauth", "jwt", "password"],
    "Technical debt / refactoring": ["tech debt", "refactor", "legacy", "rewrite", "code quality", "migration"],
    "Pricing / monetization": ["pricing", "monetiz", "freemium", "subscription", "revenue", "mrr", "arr", "billing"],
    "API design": ["api", "rest", "graphql", "trpc", "endpoint", "webhook", "versioning"],
    "Mobile / cross-platform": ["mobile", "react native", "flutter", "ios", "android", "pwa", "swift", "kotlin"],
    "Data / analytics": ["analytics", "metrics", "dashboard", "data pipeline", "observability", "datadog"],
    "Community / content creation": ["newsletter", "blog", "content", "audience", "writing", "creator", "youtube", "podcast"],
    "Entrepreneurship": ["entrepreneur", "bootstrap", "indie hacker", "saas", "acquisition", "exit", "business model"],
    "Economics": ["macroeconomics", "microeconomics", "gdp growth", "inflation rate", "interest rate", "monetary policy", "fiscal policy", "supply chain economics"],
    "AI / future of AI": ["agi", "artificial intelligence", "automation", "future of ai", "singularity", "superintelligence"],
    "Philosophy of tech": ["ethics", "digital minimalism", "philosophy", "agi risk", "alignment"],
    "AI agents": ["ai agent", "tool use", "multi-agent", "autonomous agent", "agentic", "crew", "langchain", "langgraph"],
    "Robotics / physical tech": ["robot", "drone", "embodied", "humanoid", "physical ai", "manufacturing"],
    "Current events / news": ["just launched", "just shipped", "now available", "new release", "open sourced"],
    "Culture / memes / takes": ["meme", "hot take", "viral tweet", "discourse", "ratio"],
}


def classify_topic_scored(
    text: str,
    enabled_topics: list[str],
    keyword_map: dict[str, list[str]] | None = None,
) -> tuple[str, int]:
    """Best matching enabled topic and its keyword hit score. ("", 0) if no match."""
    if keyword_map is None:
        keyword_map = TOPIC_KEYWORDS
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for topic, keywords in keyword_map.items():
        if topic not in enabled_topics:
            continue
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[topic] = score
    if not scores:
        return "", 0
    best = max(scores, key=scores.get)
    return best, scores[best]


def classify_topic(
    text: str,
    enabled_topics: list[str],
    keyword_map: dict[str, list[str]] | None = None,
) -> str:
    """Backward-compatible: best topic label or empty string."""
    topic, _ = classify_topic_scored(text, enabled_topics, keyword_map)
    return topic
