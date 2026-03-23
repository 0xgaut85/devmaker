"""Topic keywords and classification — single place for dev-mode topic matching."""

from __future__ import annotations

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "Database / backend": [
        "postgres", "sql", "database", "redis", "backend", "migration", "orm",
        "prisma", "supabase", "mongodb", "mysql", "sqlite", "dynamo", "cassandra",
        "schema", "query", "index", "caching", "cache", "server", "node.js",
        "express", "fastapi", "django", "flask", "spring", "microservice",
    ],
    "Frontend / UI / UX": [
        "frontend", "react", "css", "tailwind", "ui", "ux", "design system",
        "component", "nextjs", "next.js", "svelte", "vue", "angular", "html",
        "responsive", "animation", "figma", "web app", "jsx", "tsx", "dom",
        "browser", "layout", "accessibility", "a11y", "dark mode",
    ],
    "DevOps / infra": [
        "deploy", "ci/cd", "docker", "kubernetes", "k8s", "terraform", "aws",
        "gcp", "azure", "infra", "monitoring", "pipeline", "github actions",
        "vercel", "netlify", "cloudflare", "devops", "scaling", "uptime",
        "load balancer", "cdn", "container", "helm", "ansible",
    ],
    "AI / ML tools": [
        "gpt", "claude", "llm", "openai", "copilot", "cursor", "ai coding",
        "model", "fine-tun", "benchmark", "chatgpt", "gemini", "anthropic",
        "transformer", "neural", "deep learning", "machine learning", "ml",
        "training", "inference", "embedding", "vector", "rag", "prompt",
        "ai", "artificial intelligence",
    ],
    "Open source": [
        "open source", "open-source", "oss", "github", "contributor",
        "maintainer", "license", "fork", "pull request", "pr review",
        "repo", "repository", "star", "npm", "pypi", "crate",
    ],
    "Startup / founder life": [
        "startup", "founder", "fundrais", "pivot", "pmf", "product-market",
        "launch", "yc", "investor", "seed", "series", "co-founder",
        "bootstrapp", "pre-seed", "valuation", "pitch", "accelerator",
        "mvp", "traction", "burn rate", "runway",
    ],
    "Career / growth": [
        "hiring", "interview", "promotion", "resume", "career", "mentor",
        "salary", "job", "laid off", "layoff", "onboarding", "senior",
        "junior", "staff engineer", "tech lead", "manager", "ic",
        "work-life", "negotiate", "offer",
    ],
    "Developer tools / productivity": [
        "ide", "vscode", "terminal", "cli", "neovim", "vim", "workflow",
        "dev tools", "productivity", "automation", "script", "dotfiles",
        "git", "linter", "formatter", "debugger", "profiler", "tmux",
        "zsh", "bash",
    ],
    "Product thinking": [
        "feature", "roadmap", "user research", "ship", "prioriti", "product",
        "user feedback", "iteration", "mvp", "beta", "dogfood", "use case",
        "product sense", "scope creep", "user story",
    ],
    "Hardware / gadgets": [
        "hardware", "gadget", "device", "peripheral", "monitor", "keyboard",
        "mouse", "home office", "mechanical keyboard", "gpu", "cpu",
        "m1", "m2", "m3", "m4", "laptop", "setup", "desk",
    ],
    "Remote work / async": [
        "remote", "async", "timezone", "wfh", "hybrid", "distributed",
        "remote work", "home office", "co-working", "digital nomad",
    ],
    "Side projects": [
        "side project", "build in public", "indie", "solo", "weekend project",
        "burnout", "scope creep", "hobby project", "shipped", "building",
        "maker", "indie maker", "solo dev",
    ],
    "Security / privacy": [
        "security", "auth", "encrypt", "vulnerability", "pentest", "oauth",
        "jwt", "password", "hack", "breach", "zero-day", "cve", "csrf",
        "xss", "injection", "firewall", "2fa", "mfa",
    ],
    "Technical debt / refactoring": [
        "tech debt", "refactor", "legacy", "rewrite", "code quality",
        "migration", "cleanup", "deprecat", "technical debt", "code review",
        "code smell", "maintainab",
    ],
    "Pricing / monetization": [
        "pricing", "monetiz", "freemium", "subscription", "revenue", "mrr",
        "arr", "billing", "churn", "ltv", "conversion", "paywall",
        "stripe", "payment",
    ],
    "API design": [
        "api", "rest", "graphql", "trpc", "endpoint", "webhook", "versioning",
        "sdk", "integration", "oauth", "rate limit", "pagination",
    ],
    "Mobile / cross-platform": [
        "mobile", "react native", "flutter", "ios", "android", "pwa",
        "swift", "kotlin", "app store", "play store", "mobile app",
        "cross-platform", "expo",
    ],
    "Data / analytics": [
        "analytics", "metrics", "dashboard", "data pipeline", "observability",
        "datadog", "grafana", "prometheus", "logging", "telemetry",
        "data engineering", "etl", "warehouse",
    ],
    "Community / content creation": [
        "newsletter", "blog", "content", "audience", "writing", "creator",
        "youtube", "podcast", "substack", "medium", "twitter thread",
        "content creation", "community",
    ],
    "Entrepreneurship": [
        "entrepreneur", "bootstrap", "indie hacker", "saas", "acquisition",
        "exit", "business model", "solopreneur", "micro-saas", "revenue",
        "customer", "growth", "market fit",
    ],
    "Economics": [
        "macroeconomics", "microeconomics", "gdp growth", "inflation rate",
        "interest rate", "monetary policy", "fiscal policy",
        "supply chain economics",
    ],
    "AI / future of AI": [
        "agi", "artificial intelligence", "automation", "future of ai",
        "singularity", "superintelligence", "ai safety", "alignment",
        "ai regulation",
    ],
    "Philosophy of tech": [
        "ethics", "digital minimalism", "philosophy", "agi risk", "alignment",
        "tech ethics", "surveillance", "privacy",
    ],
    "AI agents": [
        "ai agent", "tool use", "multi-agent", "autonomous agent", "agentic",
        "crew", "langchain", "langgraph", "mcp", "function calling",
        "agent", "orchestrat",
    ],
    "Robotics / physical tech": [
        "robot", "drone", "embodied", "humanoid", "physical ai",
        "manufacturing", "3d print", "hardware startup",
    ],
    "Current events / news": [
        "just launched", "just shipped", "now available", "new release",
        "open sourced", "announcing", "released",
    ],
    "Culture / memes / takes": [
        "meme", "hot take", "viral tweet", "discourse", "ratio",
        "unpopular opinion", "controversial",
    ],
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
