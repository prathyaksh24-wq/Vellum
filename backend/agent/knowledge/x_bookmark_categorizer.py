"""Local X bookmark classification adapted from Siftly's MIT licensed design.

Siftly source: https://github.com/viperrcrypto/Siftly
Copyright (c) 2025 Siftly Contributors, MIT License.

Vellum keeps the resulting categories in Knowledge Core. This module does not
create Siftly's Prisma database, provider client, or a second ingestion path.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


TAXONOMY_VERSION = "siftly-inspired-v1"

CATEGORY_NAMES = {
    "ai-resources": "AI & Machine Learning",
    "finance-crypto": "Crypto & Web3",
    "dev-tools": "Dev Tools & Engineering",
    "finance-investing": "Finance & Investing",
    "startups-business": "Startups & Business",
    "news": "News & Politics",
    "design": "Design & Product",
    "health-wellness": "Health & Wellness",
    "security-privacy": "Security & Privacy",
    "science-research": "Science & Research",
    "productivity": "Productivity",
    "funny-memes": "Funny & Memes",
    "general": "General",
}

_CATEGORY_TERMS = {
    "ai-resources": (
        "ai", "artificial intelligence", "machine learning", "llm", "chatgpt", "claude",
        "gemini", "grok", "model", "prompt", "rag", "fine tuning", "agentic", "embedding",
    ),
    "finance-crypto": (
        "crypto", "bitcoin", "btc", "ethereum", "eth", "solana", "defi", "web3", "nft",
        "blockchain", "token", "airdrop", "wallet", "onchain", "smart contract",
    ),
    "dev-tools": (
        "github", "gitlab", "api", "code", "coding", "developer", "software", "typescript",
        "python", "rust", "golang", "database", "docker", "devops", "frontend", "backend",
        "open source", "framework", "terminal", "debug", "repository",
    ),
    "finance-investing": (
        "stocks", "stock market", "equities", "investing", "options", "portfolio", "earnings",
        "interest rate", "federal reserve", "forex", "commodities", "real estate", "macro",
    ),
    "startups-business": (
        "startup", "founder", "saas", "business", "entrepreneur", "fundraising", "venture capital",
        "product market fit", "marketing", "sales", "revenue", "bootstrapped", "y combinator",
    ),
    "news": (
        "breaking", "news", "politics", "election", "government", "policy", "geopolitics",
        "regulation", "war", "journalist", "reporting", "current events",
    ),
    "design": (
        "design", "ui", "ux", "figma", "typography", "wireframe", "brand", "creative",
        "user research", "design system", "motion", "product design",
    ),
    "health-wellness": (
        "health", "fitness", "nutrition", "sleep", "mental health", "workout", "diet",
        "meditation", "longevity", "supplement", "wellness",
    ),
    "security-privacy": (
        "security", "privacy", "cybersecurity", "vulnerability", "exploit", "malware", "phishing",
        "encryption", "vpn", "authentication", "data breach", "zero day", "pentest",
    ),
    "science-research": (
        "research", "science", "paper", "arxiv", "physics", "biology", "neuroscience", "space",
        "climate", "robotics", "quantum", "study", "scientist",
    ),
    "productivity": (
        "productivity", "workflow", "automation", "time management", "habit", "focus", "notes",
        "second brain", "obsidian", "notion", "deep work", "knowledge management",
    ),
    "funny-memes": (
        "meme", "memes", "joke", "funny", "satire", "parody", "comedy", "shitpost", "lol",
    ),
}

_TOOL_DOMAINS = {
    "github.com": ("GitHub", "dev-tools"),
    "gitlab.com": ("GitLab", "dev-tools"),
    "stackoverflow.com": ("Stack Overflow", "dev-tools"),
    "npmjs.com": ("npm", "dev-tools"),
    "pypi.org": ("PyPI", "dev-tools"),
    "docker.com": ("Docker", "dev-tools"),
    "vercel.com": ("Vercel", "dev-tools"),
    "supabase.com": ("Supabase", "dev-tools"),
    "huggingface.co": ("Hugging Face", "ai-resources"),
    "arxiv.org": ("arXiv", "science-research"),
    "openai.com": ("OpenAI", "ai-resources"),
    "anthropic.com": ("Anthropic", "ai-resources"),
    "deepmind.google": ("DeepMind", "ai-resources"),
    "figma.com": ("Figma", "design"),
    "notion.so": ("Notion", "productivity"),
    "obsidian.md": ("Obsidian", "productivity"),
    "coinbase.com": ("Coinbase", "finance-crypto"),
    "binance.com": ("Binance", "finance-crypto"),
    "uniswap.org": ("Uniswap", "finance-crypto"),
    "etherscan.io": ("Etherscan", "finance-crypto"),
}

_URL = re.compile(r"https?://[^\s)\]}>]+", re.IGNORECASE)
_HASHTAG = re.compile(r"(?<!\w)#([\w-]+)", re.UNICODE)
_MENTION = re.compile(r"(?<!\w)@([A-Za-z0-9_]{1,15})")


def categorize_bookmark(item: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(str(item.get(key) or "") for key in ("text", "title", "body", "content"))
    urls = list(dict.fromkeys([*_URL.findall(text), str(item.get("url") or "")]))
    urls = [url for url in urls if url]
    hashtags = sorted({match.casefold() for match in _HASHTAG.findall(text)})
    mentions = sorted({match.casefold() for match in _MENTION.findall(text)})
    tools: list[str] = []
    domain_categories: list[str] = []
    for url in urls:
        try:
            domain = urlparse(url).hostname or ""
        except ValueError:
            continue
        domain = domain.casefold().removeprefix("www.")
        for known, (tool, category) in _TOOL_DOMAINS.items():
            if domain == known or domain.endswith(f".{known}"):
                if tool not in tools:
                    tools.append(tool)
                domain_categories.append(category)
                break

    haystack = f" {text.casefold()} {' '.join(hashtags)} "
    scores: dict[str, float] = {}
    for category, terms in _CATEGORY_TERMS.items():
        hits = sum(1 for term in terms if _contains_term(haystack, term))
        if hits:
            scores[category] = min(0.96, 0.58 + (0.09 * hits))
    for category in domain_categories:
        scores[category] = max(scores.get(category, 0.0), 0.9)

    assignments = [
        {"category": category, "name": CATEGORY_NAMES[category], "confidence": round(score, 2)}
        for category, score in sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))[:3]
        if score >= 0.58
    ]
    if not assignments:
        assignments = [{"category": "general", "name": CATEGORY_NAMES["general"], "confidence": 0.5}]
    return {
        "assignments": assignments,
        "entities": {
            "hashtags": hashtags,
            "urls": urls,
            "mentions": mentions,
            "tools": tools,
        },
        "taxonomy_version": TAXONOMY_VERSION,
    }


def categorize_bookmarks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**item, "bookmark_intelligence": categorize_bookmark(item)} for item in items]


def _contains_term(haystack: str, term: str) -> bool:
    escaped = re.escape(term.casefold()).replace(r"\ ", r"\s+")
    return re.search(rf"(?<![\w-]){escaped}(?![\w-])", haystack) is not None
