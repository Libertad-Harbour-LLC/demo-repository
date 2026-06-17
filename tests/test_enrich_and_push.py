"""Tests for per-skill enrichment + catalog auto-push (no network/LLM).

`enrich.enrich_payload` and `catalog.push_payload` both take injectable seams
(`md_fetch`/`claude_complete`, `post`) so we exercise the full logic offline.
"""
from __future__ import annotations

import json

import pytest

from trendwatch import catalog, enrich, import_payload


# --- helpers ----------------------------------------------------------------

def _payload(decision="test_now"):
    return import_payload.assemble_payload(
        [
            import_payload.make_repo_entry(
                "Acme/social-suite", "main",
                ["instagram-reels-writer", "tiktok-hooks"],
                stars=42, category="marketing", rating=7.5, decision=decision,
            )
        ],
        "2026-06-17",
    )


# --- raw SKILL.md URL derivation --------------------------------------------

def test_raw_skill_md_url_from_deep_link():
    url = "https://github.com/Acme/social-suite/tree/main/.claude/skills/instagram-reels-writer"
    assert enrich.raw_skill_md_url(url) == (
        "https://raw.githubusercontent.com/Acme/social-suite/main/"
        ".claude/skills/instagram-reels-writer/SKILL.md"
    )


def test_raw_skill_md_url_none_on_garbage():
    assert enrich.raw_skill_md_url("https://example.com/x") is None


def test_normalize_tags_bounds_and_shape():
    tags = enrich.normalize_tags(["Instagram", "Reels!", "content_automation", "Reels", "a b"])
    assert tags == ["instagram", "reels", "content-automation", "a-b"]
    assert all(t == t.lower() for t in tags)


# --- enrichment: applies description/category/tags --------------------------

def test_enrich_fills_fields_and_validates_category():
    payload = _payload()

    def fake_md(url):
        return "# Instagram Reels writer\nGenerates short video scripts."

    def fake_claude(system, user):
        # Two skills in one batch -> ids 0 and 1
        return json.dumps({"results": [
            {"id": 0, "description": "Пишет сценарии для Reels и Шортс (Инстаграм, SMM).",
             "category": "content", "tags": ["instagram", "reels", "smm"]},
            {"id": 1, "description": "Хуки для ТикТок.",
             "category": "not-a-real-category", "tags": ["tiktok", "hooks"]},
        ]})

    suggested = enrich.enrich_payload(payload, md_fetch=fake_md, claude_complete=fake_claude)
    skills = payload["repos"][0]["skills"]
    s0, s1 = skills[0], skills[1]
    assert "Reels" in s0["description"] and s0["category"] == "content"
    assert s0["tags"] == ["instagram", "reels", "smm"]
    # invalid category falls back to the repo category (marketing), not invented
    assert s1["category"] == "marketing"
    assert suggested == []


def test_enrich_collects_suggested_category_without_assigning():
    payload = _payload()

    def fake_claude(system, user):
        return json.dumps({"results": [
            {"id": 0, "description": "d", "category": "marketing", "tags": ["a", "b", "c"]},
            {"id": 1, "description": "d2", "category": "marketing", "tags": ["d", "e", "f"],
             "suggest": {"slug": "blockchain", "name": "Блокчейн", "rationale": "on-chain"}},
        ]})

    suggested = enrich.enrich_payload(payload, md_fetch=lambda u: "x", claude_complete=fake_claude)
    assert any(s["slug"] == "blockchain" for s in suggested)
    # not assigned to the skill
    assert all(sk["category"] == "marketing" for sk in payload["repos"][0]["skills"])
    # merging into payload categories marks it suggested
    import_payload.apply_category_updates(payload, suggested)
    cats = {c["slug"]: c for c in payload["categories"]}
    assert cats["blockchain"]["status"] == "suggested"


def test_enrich_only_touches_test_now_repos():
    payload = _payload(decision="watch")
    called = {"n": 0}

    def fake_claude(system, user):
        called["n"] += 1
        return json.dumps({"results": []})

    enrich.enrich_payload(payload, md_fetch=lambda u: "x", claude_complete=fake_claude)
    assert called["n"] == 0  # watch repo skipped entirely


def test_enrich_caps_fetches_to_max_per_repo():
    payload = import_payload.assemble_payload(
        [import_payload.make_repo_entry(
            "Acme/big", "main", [f"skill-{i}" for i in range(20)], category="general")],
        "2026-06-17",
    )
    fetches = {"n": 0}

    def counting_fetch(url):
        fetches["n"] += 1
        return "x"

    enrich.enrich_payload(
        payload, md_fetch=counting_fetch, claude_complete=lambda s, u: '{"results": []}',
        batch_size=5, max_per_repo=7,
    )
    assert fetches["n"] == 7


def test_enrich_no_completer_is_noop(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    payload = _payload()
    out = enrich.enrich_payload(payload, md_fetch=lambda u: "x")  # claude_complete=None
    assert out == []
    assert "description" not in payload["repos"][0]["skills"][0]


# --- catalog push -----------------------------------------------------------

class _Resp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def test_push_sends_secret_header_and_returns_json():
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["body"] = json
        return _Resp(200, {"ok": True, "repos": 1, "skills": 2, "skipped": 0, "suggested": []})

    result, error = catalog.push_payload(
        _payload(), secret="s3cr3t", post=fake_post,
    )
    assert error is None
    assert result["ok"] is True
    assert captured["headers"]["x-radar-secret"] == "s3cr3t"
    assert captured["headers"]["Content-Type"] == "application/json"
    assert captured["body"]["radar_version"] == "1.0"


def test_push_without_secret_is_skipped():
    result, error = catalog.push_payload(_payload(), secret="", post=lambda *a, **k: _Resp())
    assert result is None and "SKILL_RADAR_INGEST_SECRET" in error


def test_push_empty_payload_skipped():
    empty = import_payload.assemble_payload([], "2026-06-17")
    result, error = catalog.push_payload(empty, secret="x", post=lambda *a, **k: _Resp())
    assert result is None and "empty payload" in error


def test_push_non_200_returns_error():
    result, error = catalog.push_payload(
        _payload(), secret="x",
        post=lambda *a, **k: _Resp(403, text="forbidden"),
    )
    assert result is None and "HTTP 403" in error


def test_format_summary_and_suggested():
    resp = {"ok": True, "repos": 3, "skills": 40, "skipped": 1, "suggested": [{"slug": "x"}]}
    assert "repos=3" in catalog.format_summary(resp)
    assert "suggested=1" in catalog.format_summary(resp)
    assert catalog.suggested_categories(resp) == [{"slug": "x"}]
