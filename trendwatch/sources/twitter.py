"""X/Twitter source via Apify actor."""
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

try:
    from .. import config
except Exception:
    import config  # type: ignore


def _parse_created(value: str):
    if not value:
        return None
    try:
        # Common Twitter format: "Wed Oct 10 12:00:00 +0000 2023"
        return datetime.strptime(value, "%a %b %d %H:%M:%S %z %Y")
    except Exception:
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def fetch_twitter(keywords: list[str], max_items: int = 10, since_hours: int = 24) -> list[dict]:
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        print("[trendwatch:twitter] APIFY_API_TOKEN not set, skipping", file=sys.stderr)
        return []
    try:
        # Apify actor slug uses '~' between user and actor name in the API path
        actor = getattr(config, "APIFY_TWITTER_ACTOR", "apidojo~tweet-scraper")
        url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items?token={token}"
        body = {
            "searchTerms": keywords,
            "sort": "Latest",
            "maxItems": max_items,
            "tweetLanguage": "en",
        }
        resp = requests.post(url, json=body, timeout=240)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list):
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        items: list[dict] = []
        for tw in data:
            text = (tw.get("text") or tw.get("fullText") or "").strip()
            link = tw.get("url") or tw.get("twitterUrl") or ""
            if not text or not link:
                continue
            author = ""
            a = tw.get("author") or tw.get("user") or {}
            if isinstance(a, dict):
                author = a.get("userName") or a.get("username") or a.get("screen_name") or ""
            created_raw = tw.get("createdAt") or tw.get("created_at")
            created = _parse_created(created_raw) if created_raw else None
            if created and created < cutoff:
                continue
            items.append({
                "source": "twitter",
                "title": text[:120].replace("\n", " "),
                "url": link,
                "meta": f"@{author}" if author else "",
            })
            if len(items) >= max_items:
                break
        return items
    except Exception as exc:
        print(f"[trendwatch:twitter] error: {exc}", file=sys.stderr)
        return []
