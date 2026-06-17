"""Reddit subreddit source.

Sprint 3: post-filter by keywords (config.REDDIT_KEYWORDS_FILTER) so we only
keep posts that look like they're about Claude Code Skills, not generic AI
chatter.

Auth: Reddit blocks anonymous requests from datacenter IPs (GitHub Actions
runners answer ``403 Blocked`` — observed in every production run), so the
public ``www.reddit.com/*.json`` endpoint only works from residential IPs.
When ``REDDIT_CLIENT_ID`` + ``REDDIT_CLIENT_SECRET`` env vars are set
(create a "script" app at reddit.com/prefs/apps), we use the official
app-only OAuth flow instead: token from ``/api/v1/access_token``, data from
``oauth.reddit.com`` — which is allowed from CI. Without creds we fall back
to the public endpoint (fine locally, dead in Actions).
"""
import os
import sys
import time

import requests

PUBLIC_BASE = "https://www.reddit.com"
OAUTH_BASE = "https://oauth.reddit.com"
TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
USER_AGENT = "trendwatch/1.0 (daily skills digest)"

HEADERS = {"User-Agent": USER_AGENT}

# Module-level token cache — one token per process run is plenty
# (app-only tokens live 24h; the cron run takes minutes).
_token_cache: list[str | None] = [None]


def _oauth_token() -> str | None:
    """Fetch (and cache) an app-only OAuth token. None if creds unset/fail."""
    if _token_cache[0]:
        return _token_cache[0]
    client_id = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None
    try:
        resp = requests.post(
            TOKEN_URL,
            auth=(client_id, client_secret),
            data={"grant_type": "client_credentials"},
            headers=HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        token = (resp.json() or {}).get("access_token") or ""
        if token:
            _token_cache[0] = token
            return token
        print("[trendwatch:reddit] OAuth token response had no access_token",
              file=sys.stderr)
    except Exception as exc:
        print(f"[trendwatch:reddit] OAuth token fetch failed: {exc}",
              file=sys.stderr)
    return None


def _fetch_new_json(sub: str) -> list[dict]:
    """Return the /new listing children for a subreddit via OAuth when
    possible, else the public endpoint. Raises on HTTP errors so the caller's
    per-subreddit try/except logs and moves on."""
    token = _oauth_token()
    if token:
        url = f"{OAUTH_BASE}/r/{sub}/new?limit=50"
        headers = {**HEADERS, "Authorization": f"Bearer {token}"}
    else:
        url = f"{PUBLIC_BASE}/r/{sub}/new.json?limit=50"
        headers = HEADERS
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json().get("data", {}).get("children", []) or []


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
                children = _fetch_new_json(sub)
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
