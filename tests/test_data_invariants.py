"""Schema invariants on the JSON the bot actually reads in production.

Each invariant here was added in response to a real bug or near-miss. The
prior backfill of 12 missing-description entries (PR #17, #24) would have
been caught instantly by test_recommended_has_description.
"""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

REC_PATHS = [
    ROOT / "digests" / "recommended.json",
    ROOT / "digests" / "workflows" / "recommended.json",
]

WATCH_PATHS = [
    ROOT / "digests" / "watchlist.json",
    ROOT / "digests" / "workflows" / "watchlist.json",
]


def _recommended_items():
    for p in REC_PATHS:
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        skills = data.get("skills") or {}
        for url, item in skills.items():
            yield p.name, url, item


def _watch_items():
    for p in WATCH_PATHS:
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        items = data.get("items") or {}
        for url, item in items.items():
            yield p.name, url, item


def test_every_recommended_has_description():
    """The 📝 block on the detail screen requires a non-empty description.
    Missing one means the bot renders a blank card for that item.
    """
    missing = [
        f"{src}: {item.get('repo_full_name')}"
        for src, _, item in _recommended_items()
        if not (item.get("description") or "").strip()
    ]
    assert not missing, f"items missing description:\n  " + "\n  ".join(missing)


def test_every_recommended_has_url():
    missing = [
        f"{src}: {item.get('repo_full_name')}"
        for src, url, item in _recommended_items()
        if not (item.get("url") or "").startswith("http")
    ]
    assert not missing, f"items missing url:\n  " + "\n  ".join(missing)


def test_dict_key_matches_url_field():
    """The top-level dict key in recommended.json is the canonical URL.
    Drift between the two breaks find_by_url_id (which hashes item['url']).
    """
    mismatches = [
        f"{src}: key={url!r} field={item.get('url')!r}"
        for src, url, item in _recommended_items()
        if item.get("url") != url
    ]
    assert not mismatches, "key/url drift:\n  " + "\n  ".join(mismatches)


def test_every_watch_item_has_signal_to_wait():
    """Watch items render `signal_to_wait` on the detail screen. Empty
    means the user sees a blank "Сигнал ожидания" section.
    """
    missing = [
        f"{src}: {item.get('repo_full_name')}"
        for src, _, item in _watch_items()
        if not (item.get("signal_to_wait") or "").strip()
    ]
    assert not missing, "watch items missing signal:\n  " + "\n  ".join(missing)
