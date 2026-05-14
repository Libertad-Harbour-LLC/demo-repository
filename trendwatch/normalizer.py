"""Cross-source tool/project name extraction and aggregation.

Pulls candidate tool names out of titles/URLs from each source, normalizes
them, and counts how many sources mentioned each one. Output feeds the LLM so
it can see "cursor was mentioned in 3 sources today, lovable in 1".
"""
from __future__ import annotations

import re
from typing import Iterable

# Common AI marketing / vibe-coding tools we want to recognize verbatim.
KNOWN_TOOLS: list[str] = [
    "cursor",
    "claude",
    "claude-code",
    "claude code",
    "claude skills",
    "anthropic skills",
    "gpt",
    "chatgpt",
    "copilot",
    "github copilot",
    "lovable",
    "bolt",
    "bolt.new",
    "replit",
    "replit agent",
    "v0",
    "vercel",
    "supabase",
    "langchain",
    "langgraph",
    "llamaindex",
    "crewai",
    "autogen",
    "n8n",
    "make.com",
    "zapier",
    "windsurf",
    "codeium",
    "aider",
    "continue",
    "cline",
    "perplexity",
    "anthropic",
    "openai",
    "gemini",
    "mistral",
    "ollama",
    "huggingface",
    "vercel ai",
]

# Canonicalization: map raw token -> stable display name.
_ALIASES: dict[str, str] = {
    "claude code": "claude-code",
    "cursor ai": "cursor",
    "cursor.ai": "cursor",
    "github copilot": "copilot",
    "chat gpt": "chatgpt",
    "gpt-4": "gpt",
    "gpt4": "gpt",
    "gpt-5": "gpt",
    "gpt5": "gpt",
    "bolt.new": "bolt",
    "vercel ai": "vercel",
    "make.com": "make",
    "hugging face": "huggingface",
    "replit agent": "replit",
}

_STOP_WORDS = {
    "The",
    "This",
    "That",
    "These",
    "Those",
    "How",
    "Why",
    "What",
    "When",
    "Where",
    "Who",
    "AI",
    "API",
    "LLM",
    "GPT",
    "MCP",
    "SDK",
    "CLI",
    "GUI",
    "IDE",
    "PR",
    "OS",
    "UI",
    "UX",
    "JSON",
    "YAML",
    "HTTP",
    "URL",
    "I",
    "We",
    "You",
    "My",
    "Our",
    "Your",
    "New",
    "Best",
    "Top",
    "Show",
    "Ask",
    "HN",
    "Reddit",
    "GitHub",
    "Twitter",
    "Threads",
}

_PUNCT_RE = re.compile(r"[^\w\s.\-]+", re.UNICODE)
_CAPS_RE = re.compile(r"\b[A-Z][A-Za-z0-9]{2,}\b")


def _canonical(name: str) -> str:
    name = name.strip().lower()
    name = _PUNCT_RE.sub(" ", name).strip()
    name = re.sub(r"\s+", " ", name)
    if name in _ALIASES:
        return _ALIASES[name]
    # Try alias keys without spaces (e.g. "claude-code" already canonical).
    return name


def _extract_known(text: str) -> set[str]:
    """Find any KNOWN_TOOLS phrase appearing in text (case-insensitive)."""
    if not text:
        return set()
    low = text.lower()
    hits: set[str] = set()
    for tool in KNOWN_TOOLS:
        pat = r"(?<![\w-])" + re.escape(tool.lower()) + r"(?![\w-])"
        if re.search(pat, low):
            hits.add(_canonical(tool))
    return hits


def _extract_caps(text: str) -> set[str]:
    """Pull capitalized words >=3 chars as candidate product names."""
    if not text:
        return set()
    out: set[str] = set()
    for tok in _CAPS_RE.findall(text):
        if tok in _STOP_WORDS:
            continue
        if len(tok) < 3:
            continue
        out.add(_canonical(tok))
    return out


def _github_names(item: dict) -> set[str]:
    """For GitHub items use the owner/repo as canonical, plus the repo segment."""
    names: set[str] = set()
    title = item.get("title", "")
    if "/" in title:
        names.add(_canonical(title))
        repo_segment = title.split("/", 1)[1]
        if repo_segment:
            names.add(_canonical(repo_segment))
    url = item.get("url", "")
    if url:
        tail = url.rstrip("/").rsplit("/", 1)[-1]
        if tail:
            names.add(_canonical(tail))
    return {n for n in names if n}


def _candidates(item: dict) -> set[str]:
    source = item.get("source", "")
    title = item.get("title", "") or ""
    if source == "github":
        names = _github_names(item)
    else:
        names = set()
    names |= _extract_known(title)
    if source != "github":
        names |= _extract_caps(title)
    return {n for n in names if n and len(n) >= 3}


def normalize(
    items_by_source: dict[str, list[dict]],
) -> tuple[list[dict], list[dict]]:
    """Aggregate cross-source mentions plus return items annotated with names.

    Returns ``(top_mentions, annotated_items)``.

    ``top_mentions`` is a list of dicts sorted by total mention count (desc),
    capped at 30. ``annotated_items`` is a flat list of the original items with
    an extra ``matched_names`` field so the LLM can cross-reference.
    """
    counters: dict[str, dict] = {}
    annotated: list[dict] = []

    for source, items in (items_by_source or {}).items():
        for it in items or []:
            enriched = dict(it)
            enriched.setdefault("source", source)
            names = _candidates(enriched)
            enriched["matched_names"] = sorted(names)
            annotated.append(enriched)
            for name in names:
                slot = counters.setdefault(
                    name,
                    {
                        "name": name,
                        "mentions": {
                            "github": 0,
                            "reddit": 0,
                            "twitter": 0,
                            "threads": 0,
                            "total": 0,
                        },
                        "urls": [],
                        "sample_titles": [],
                    },
                )
                bucket = slot["mentions"]
                if source in bucket:
                    bucket[source] += 1
                bucket["total"] += 1
                url = enriched.get("url")
                if url and url not in slot["urls"]:
                    slot["urls"].append(url)
                title = enriched.get("title")
                if title and title not in slot["sample_titles"]:
                    if len(slot["sample_titles"]) < 5:
                        slot["sample_titles"].append(title)

    top = sorted(
        counters.values(), key=lambda r: r["mentions"]["total"], reverse=True
    )[:30]
    return top, annotated


def annotate_only(items_by_source: dict[str, list[dict]]) -> list[dict]:
    """Convenience: return just the annotated items list."""
    _, annotated = normalize(items_by_source)
    return annotated


__all__ = ["KNOWN_TOOLS", "normalize", "annotate_only"]


def _maybe_iterable(x: Iterable | None) -> Iterable:  # pragma: no cover - utility
    return x or []
