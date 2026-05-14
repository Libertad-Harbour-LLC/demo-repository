"""Reddit source for the workflows pipeline.

Thin wrapper around ``trendwatch.sources.reddit.fetch_reddit`` that adds
workflow-specific ``tool`` and ``source`` labels based on the subreddit
the post came from (parsed out of the meta string built by trendwatch).
"""
from __future__ import annotations

from trendwatch.sources.reddit import fetch_reddit as _fetch


def _detect_tool_from_meta(meta: str) -> str:
    if not meta:
        return "other"
    low = meta.lower()
    # meta is built as "r/<sub> • ↑N • Mcomments • match: <kw>"
    if "r/n8n" in low or "/n8n" in low:
        return "n8n"
    if "r/makeautomations" in low or "r/integromat" in low or "make" in low:
        return "make"
    return "other"


def fetch_reddit(
    subreddits: list[str],
    min_score: int,
    since_hours: int,
    max_items: int,
    keywords_filter: list[str] | None,
) -> list[dict]:
    items = _fetch(
        subreddits,
        min_score,
        since_hours,
        max_items,
        keywords_filter,
    )
    out: list[dict] = []
    for it in items or []:
        tool = _detect_tool_from_meta(it.get("meta", ""))
        new_it = dict(it)
        new_it["tool"] = tool
        new_it["source"] = f"reddit_{tool}"
        out.append(new_it)
    return out


__all__ = ["fetch_reddit"]
