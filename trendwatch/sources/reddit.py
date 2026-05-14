"""Reddit subreddit source via public new.json endpoint."""
import sys
import time

import requests

HEADERS = {"User-Agent": "trendwatch/1.0"}


def fetch_reddit(
    subreddits: list[str],
    min_score: int = 20,
    since_hours: int = 24,
    max_items: int = 10,
) -> list[dict]:
    try:
        cutoff = time.time() - since_hours * 3600
        collected: list[dict] = []
        for sub in subreddits:
            try:
                url = f"https://www.reddit.com/r/{sub}/new.json?limit=50"
                resp = requests.get(url, headers=HEADERS, timeout=30)
                resp.raise_for_status()
                children = resp.json().get("data", {}).get("children", [])
            except Exception as exc:
                print(f"[trendwatch:reddit:{sub}] error: {exc}", file=sys.stderr)
                continue
            for child in children:
                data = child.get("data", {})
                score = data.get("score", 0)
                created = data.get("created_utc", 0)
                if score < min_score or created < cutoff:
                    continue
                title = (data.get("title") or "")[:120]
                permalink = data.get("permalink", "")
                collected.append({
                    "source": "reddit",
                    "title": title,
                    "url": "https://www.reddit.com" + permalink,
                    "meta": f"r/{data.get('subreddit', sub)} • ↑{score} • {data.get('num_comments', 0)}\U0001f4ac",
                    "_score": score,
                })
        collected.sort(key=lambda x: x.get("_score", 0), reverse=True)
        items = collected[:max_items]
        for it in items:
            it.pop("_score", None)
        return items
    except Exception as exc:
        print(f"[trendwatch:reddit] error: {exc}", file=sys.stderr)
        return []
