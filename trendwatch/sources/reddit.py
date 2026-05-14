"""Reddit subreddit source via public new.json endpoint.

Sprint 3: post-filter by keywords (config.REDDIT_KEYWORDS_FILTER) so we only
keep posts that look like they're about Claude Code Skills, not generic AI
chatter.
"""
import sys
import time

import requests

HEADERS = {"User-Agent": "trendwatch/1.0"}


def _match_keyword(text: str, keywords: list[str]) -> str | None:
    """Return the first keyword (lowercased) that occurs in text, or None."""
    if not text or not keywords:
        return None
    low = text.lower()
    for kw in keywords:
        if not kw:
            continue
        if kw.lower() in low:
            return kw
    return None


def fetch_reddit(
    subreddits: list[str],
    min_score: int = 5,
    since_hours: int = 24,
    max_items: int = 15,
    keywords_filter: list[str] | None = None,
) -> list[dict]:
    try:
        cutoff = time.time() - since_hours * 3600
        collected: list[dict] = []
        for sub in subreddits or []:
            try:
                url = f"https://www.reddit.com/r/{sub}/new.json?limit=50"
                resp = requests.get(url, headers=HEADERS, timeout=30)
                resp.raise_for_status()
                children = resp.json().get("data", {}).get("children", []) or []
            except Exception as exc:
                print(f"[trendwatch:reddit:{sub}] error: {exc}", file=sys.stderr)
                continue
            for child in children:
                data = (child or {}).get("data", {}) or {}
                score = data.get("score") or 0
                created = data.get("created_utc") or 0
                if score < min_score or created < cutoff:
                    continue
                title = (data.get("title") or "")[:120]
                selftext = data.get("selftext") or ""
                if keywords_filter:
                    matched = _match_keyword(title, keywords_filter) or _match_keyword(
                        selftext, keywords_filter
                    )
                    if not matched:
                        continue
                else:
                    matched = None
                permalink = data.get("permalink") or ""
                meta_parts = [
                    f"r/{data.get('subreddit') or sub}",
                    f"↑{score}",
                    f"{data.get('num_comments') or 0}\U0001f4ac",
                ]
                if matched:
                    meta_parts.append(f"match: {matched}")
                collected.append(
                    {
                        "source": "reddit",
                        "title": title,
                        "url": "https://www.reddit.com" + permalink,
                        "meta": " • ".join(meta_parts),
                        "_score": score,
                    }
                )
        collected.sort(key=lambda x: x.get("_score", 0), reverse=True)
        items = collected[:max_items]
        for it in items:
            it.pop("_score", None)
        return items
    except Exception as exc:
        print(f"[trendwatch:reddit] error: {exc}", file=sys.stderr)
        return []
