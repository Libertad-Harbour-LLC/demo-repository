"""Threads source via Apify actor."""
import os
import sys

import requests

try:
    from .. import config
except Exception:
    import config  # type: ignore


def fetch_threads(keywords: list[str], max_items: int = 10) -> list[dict]:
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        print("[trendwatch:threads] APIFY_API_TOKEN not set, skipping", file=sys.stderr)
        return []
    try:
        # Apify actor slug uses '~' separator in API path
        actor = getattr(config, "APIFY_THREADS_ACTOR", "apify~threads-scraper")
        url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?token={token}"
        body = {"searchQueries": keywords, "maxItems": max_items}
        resp = requests.post(url, json=body, timeout=240)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            return []
        items: list[dict] = []
        for post in data:
            if not isinstance(post, dict):
                continue
            text = (post.get("text") or post.get("caption") or post.get("content") or "").strip()
            link = post.get("url") or post.get("postUrl") or post.get("link") or ""
            username = (
                post.get("username")
                or post.get("userName")
                or (post.get("user") or {}).get("username")
                or (post.get("author") or {}).get("username")
                or ""
            )
            if not text or not link:
                continue
            items.append({
                "source": "threads",
                "title": text[:120].replace("\n", " "),
                "url": link,
                "meta": f"@{username}" if username else "",
            })
            if len(items) >= max_items:
                break
        return items
    except Exception as exc:
        print(f"[trendwatch:threads] error: {exc}", file=sys.stderr)
        return []
