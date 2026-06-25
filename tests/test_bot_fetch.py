"""Bot data-fetch routing: private repos need the authenticated contents API.

raw.githubusercontent.com returns 404 for a private repo without auth, which
empties the bot (categories show 0, lists show "Пусто"). When a read token is
set the fetch must route through api.github.com/.../contents with the raw Accept
header; without a token it falls back to the plain raw URL (public repos).
"""
from __future__ import annotations

import pytest

from api import telegram as tg

RAW = "https://raw.githubusercontent.com/Owner/Repo/main/digests/recommended.json"


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"skills": {"u": {}}}

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _clear_cache():
    tg._cache.clear()
    yield
    tg._cache.clear()


def test_token_routes_through_contents_api(monkeypatch):
    monkeypatch.setattr(tg, "GITHUB_READ_TOKEN", "tok123")
    captured = {}

    def fake_get(url, timeout=None, headers=None):
        captured["url"] = url
        captured["headers"] = headers or {}
        return _Resp(200, {"skills": {"x": {}}})

    monkeypatch.setattr(tg.requests, "get", fake_get)
    out = tg._http_get_json(RAW)
    assert out == {"skills": {"x": {}}}
    assert captured["url"] == (
        "https://api.github.com/repos/Owner/Repo/contents/"
        "digests/recommended.json?ref=main"
    )
    assert captured["headers"]["Authorization"] == "Bearer tok123"
    assert captured["headers"]["Accept"] == "application/vnd.github.raw"


def test_no_token_uses_plain_raw(monkeypatch):
    monkeypatch.setattr(tg, "GITHUB_READ_TOKEN", "")
    captured = {}

    def fake_get(url, timeout=None, headers=None):
        captured["url"] = url
        return _Resp(200)

    monkeypatch.setattr(tg.requests, "get", fake_get)
    tg._http_get_json(RAW)
    assert captured["url"] == RAW  # untouched raw URL


def test_non_raw_url_with_token_is_not_rewritten(monkeypatch):
    monkeypatch.setattr(tg, "GITHUB_READ_TOKEN", "tok")
    captured = {}
    monkeypatch.setattr(tg.requests, "get",
                        lambda url, timeout=None, headers=None: captured.update(url=url) or _Resp())
    tg._http_get_json("https://example.com/x.json")
    assert captured["url"] == "https://example.com/x.json"


def test_fetch_url_returns_empty_on_404_then_caches(monkeypatch):
    monkeypatch.setattr(tg, "GITHUB_READ_TOKEN", "")
    monkeypatch.setattr(tg.requests, "get",
                        lambda url, timeout=None, headers=None: _Resp(404))
    out = tg._fetch_url(RAW, {"skills": {}})
    assert out == {"skills": {}}


def test_fetch_url_parses_200(monkeypatch):
    monkeypatch.setattr(tg, "GITHUB_READ_TOKEN", "tok")
    monkeypatch.setattr(tg.requests, "get",
                        lambda url, timeout=None, headers=None: _Resp(200, {"skills": {"a": {"url": "u"}}}))
    out = tg._fetch_url(RAW, {"skills": {}})
    assert out["skills"]["a"]["url"] == "u"
