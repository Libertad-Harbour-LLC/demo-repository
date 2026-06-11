"""Regression tests for the 2026-06-11 production discovery outage.

Production logs showed two completely dead channels:

1. GitHub code search: every query answered ``429 Too Many Requests``
   (secondary rate limit) — the old ``_safe_get`` only recognised the
   403-with-remaining=0 shape, so 429 raised, was swallowed, and the channel
   silently contributed zero candidates. → ``get_json_with_backoff`` must
   honour Retry-After, retry, and only then return RATE_LIMITED.

2. Reddit: every subreddit answered ``403 Blocked`` (datacenter IP block).
   → with REDDIT_CLIENT_ID/SECRET set, the fetcher must switch to the
   OAuth endpoint instead of the public one.
"""
from __future__ import annotations

import pytest


class _Resp:
    def __init__(self, status_code: int, headers: dict | None = None,
                 payload: dict | None = None):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


# --- get_json_with_backoff --------------------------------------------------

def test_429_with_retry_after_is_retried_then_succeeds(monkeypatch):
    from trendwatch.sources import _http

    responses = [
        _Resp(429, headers={"Retry-After": "7"}),
        _Resp(200, payload={"items": [1, 2]}),
    ]
    calls = {"n": 0}

    def fake_get(url, headers=None, params=None, timeout=None):
        resp = responses[calls["n"]]
        calls["n"] += 1
        return resp

    sleeps: list[int] = []
    monkeypatch.setattr(_http.requests, "get", fake_get)
    out = _http.get_json_with_backoff(
        "https://api.github.com/search/code",
        headers={}, tag="t", sleep=sleeps.append,
    )
    assert out == {"items": [1, 2]}
    assert sleeps == [7]  # honoured Retry-After


def test_429_persisting_returns_rate_limited_sentinel(monkeypatch):
    from trendwatch.sources import _http

    monkeypatch.setattr(
        _http.requests, "get",
        lambda *a, **k: _Resp(429, headers={"Retry-After": "5"}),
    )
    sleeps: list[int] = []
    out = _http.get_json_with_backoff(
        "https://api.github.com/search/code",
        headers={}, max_retries=2, tag="t", sleep=sleeps.append,
    )
    assert out == _http.RATE_LIMITED
    assert len(sleeps) == 2  # slept before each retry, then gave up


def test_403_secondary_with_retry_after_is_treated_as_rate_limit(monkeypatch):
    from trendwatch.sources import _http

    monkeypatch.setattr(
        _http.requests, "get",
        lambda *a, **k: _Resp(403, headers={"Retry-After": "3"}),
    )
    out = _http.get_json_with_backoff(
        "https://x", headers={}, max_retries=0, tag="t", sleep=lambda s: None,
    )
    assert out == _http.RATE_LIMITED


def test_retry_after_is_capped(monkeypatch):
    from trendwatch.sources import _http

    responses = [
        _Resp(429, headers={"Retry-After": "99999"}),
        _Resp(200, payload={}),
    ]
    calls = {"n": 0}

    def fake_get(*a, **k):
        resp = responses[calls["n"]]
        calls["n"] += 1
        return resp

    sleeps: list[int] = []
    monkeypatch.setattr(_http.requests, "get", fake_get)
    _http.get_json_with_backoff("https://x", headers={}, tag="t",
                                sleep=sleeps.append)
    assert sleeps == [_http.MAX_RETRY_AFTER_SECONDS]


def test_404_returns_none_without_retry(monkeypatch):
    from trendwatch.sources import _http

    monkeypatch.setattr(_http.requests, "get", lambda *a, **k: _Resp(404))
    assert _http.get_json_with_backoff("https://x", headers={}, tag="t") is None


def test_gh_search_token_preferred_over_github_token(monkeypatch):
    from trendwatch.sources import _http

    monkeypatch.setenv("GITHUB_TOKEN", "actions-token")
    monkeypatch.setenv("GH_SEARCH_TOKEN", "user-pat")
    h = _http.build_github_headers("ua")
    assert h["Authorization"] == "Bearer user-pat"

    monkeypatch.delenv("GH_SEARCH_TOKEN")
    h = _http.build_github_headers("ua")
    assert h["Authorization"] == "Bearer actions-token"


# --- Reddit OAuth path -------------------------------------------------------

@pytest.fixture(autouse=True)
def _fresh_token_cache():
    from trendwatch.sources import reddit
    reddit._token_cache[0] = None
    yield
    reddit._token_cache[0] = None


def test_reddit_uses_oauth_endpoint_when_creds_set(monkeypatch):
    from trendwatch.sources import reddit

    monkeypatch.setenv("REDDIT_CLIENT_ID", "cid")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "csec")

    posted: dict = {}

    def fake_post(url, auth=None, data=None, headers=None, timeout=None):
        posted["url"] = url
        posted["auth"] = auth
        return _Resp(200, payload={"access_token": "tok123"})

    fetched: dict = {}

    def fake_get(url, headers=None, timeout=None):
        fetched["url"] = url
        fetched["auth_header"] = (headers or {}).get("Authorization", "")
        return _Resp(200, payload={"data": {"children": []}})

    monkeypatch.setattr(reddit.requests, "post", fake_post)
    monkeypatch.setattr(reddit.requests, "get", fake_get)

    out = reddit.fetch_reddit(["ClaudeAI"], min_score=1, max_items=5)
    assert out == []
    assert posted["url"] == reddit.TOKEN_URL
    assert posted["auth"] == ("cid", "csec")
    assert fetched["url"].startswith(reddit.OAUTH_BASE)
    assert fetched["auth_header"] == "Bearer tok123"


def test_reddit_falls_back_to_public_endpoint_without_creds(monkeypatch):
    from trendwatch.sources import reddit

    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)

    fetched: dict = {}

    def fake_get(url, headers=None, timeout=None):
        fetched["url"] = url
        return _Resp(200, payload={"data": {"children": []}})

    monkeypatch.setattr(reddit.requests, "get", fake_get)
    reddit.fetch_reddit(["ClaudeAI"], min_score=1, max_items=5)
    assert fetched["url"].startswith(reddit.PUBLIC_BASE)


def test_reddit_token_fetch_failure_degrades_to_public(monkeypatch):
    from trendwatch.sources import reddit

    monkeypatch.setenv("REDDIT_CLIENT_ID", "cid")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "csec")

    def fake_post(*a, **k):
        raise RuntimeError("auth endpoint down")

    fetched: dict = {}

    def fake_get(url, headers=None, timeout=None):
        fetched["url"] = url
        return _Resp(200, payload={"data": {"children": []}})

    monkeypatch.setattr(reddit.requests, "post", fake_post)
    monkeypatch.setattr(reddit.requests, "get", fake_get)
    out = reddit.fetch_reddit(["ClaudeAI"], min_score=1, max_items=5)
    assert out == []  # no crash
    assert fetched["url"].startswith(reddit.PUBLIC_BASE)


# --- No more OR queries (legacy code search ANDs terms; OR is unsupported) ---

def test_no_or_operator_in_any_code_search_query():
    from trendwatch import config as skills_cfg
    from workflows import config as wf_cfg

    all_queries = (
        list(skills_cfg.GITHUB_CODE_QUERIES)
        + list(wf_cfg.GITHUB_CODE_QUERIES_N8N)
        + list(wf_cfg.GITHUB_CODE_QUERIES_MAKE)
    )
    offenders = [q for q in all_queries if " OR " in q]
    assert not offenders, (
        f"legacy /search/code does not support OR; rewrite as single-term "
        f"queries: {offenders}"
    )
