"""GitHub trending repos source."""
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

API_URL = "https://api.github.com/search/repositories"


def _headers() -> dict:
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "trendwatch",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def fetch_github(topics: list[str], since_hours: int = 24, max_items: int = 10) -> list[dict]:
    try:
        since_date = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).date().isoformat()
        per_page = max(1, min(20, max_items))
        seen: dict[str, dict] = {}
        for topic in topics:
            q = f"topic:{topic} created:>{since_date}"
            params = {"q": q, "sort": "stars", "order": "desc", "per_page": per_page}
            resp = requests.get(API_URL, headers=_headers(), params=params, timeout=30)
            resp.raise_for_status()
            for repo in resp.json().get("items", []):
                full_name = repo.get("full_name")
                if not full_name or full_name in seen:
                    continue
                desc = (repo.get("description") or "").strip()
                seen[full_name] = {
                    "source": "github",
                    "title": full_name,
                    "url": repo.get("html_url", ""),
                    "meta": f"⭐ {repo.get('stargazers_count', 0)} • {desc[:80]}",
                    "_score": repo.get("stargazers_count", 0),
                }
        items = sorted(seen.values(), key=lambda x: x.get("_score", 0), reverse=True)[:max_items]
        for it in items:
            it.pop("_score", None)
        return items
    except Exception as exc:
        print(f"[trendwatch:github] error: {exc}", file=sys.stderr)
        return []
