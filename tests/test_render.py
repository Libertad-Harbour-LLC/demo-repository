"""Render every item in the live recommended.json and assert basic invariants.

Catches: detail-screen rendering bugs, items that produce text over
Telegram's 4096-char message limit, route-callback fragments longer than
Telegram's 64-byte callback_data limit.
"""
import json
from pathlib import Path

from api.telegram import (
    _format_detail_recommended,
    _format_detail_watch,
    _format_item_line,
    _url_id,
)

ROOT = Path(__file__).resolve().parent.parent
TELEGRAM_MSG_LIMIT = 4096
TELEGRAM_CALLBACK_LIMIT = 64


def _items_for_source(source_key: str, rel_path: str):
    p = ROOT / rel_path
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return [(source_key, it) for it in (data.get("skills") or {}).values()]


def _all_recommended():
    return (
        _items_for_source("skills", "digests/recommended.json")
        + _items_for_source("n8n", "digests/workflows/recommended.json")
        + _items_for_source("make", "digests/workflows/recommended.json")
    )


def test_every_recommended_renders_detail():
    for source_key, item in _all_recommended():
        text = _format_detail_recommended(item, source_key)
        assert isinstance(text, str) and text, item.get("repo_full_name")
        assert len(text) < TELEGRAM_MSG_LIMIT, (
            f"detail too long ({len(text)} chars): "
            f"{item.get('repo_full_name')}"
        )


def test_every_recommended_renders_line():
    """The list-row rendering (one line per item on /list etc.)."""
    for source_key, item in _all_recommended():
        line = _format_item_line(item, source_key)
        assert isinstance(line, str) and line, item.get("repo_full_name")


def test_callback_data_under_telegram_limit():
    """Item-level callback_data carries an 8-char url_id and never exceeds
    Telegram's 64-byte limit, no matter how long repo_full_name is.
    """
    for source_key, item in _all_recommended():
        uid = _url_id(item.get("url") or "")
        for action in ("item", "explain", "share", "setup", "similar"):
            cb = f"src:{source_key}:{action}:{uid}"
            assert len(cb.encode("utf-8")) <= TELEGRAM_CALLBACK_LIMIT, (
                f"callback too long: {cb!r}"
            )


def _all_watch():
    out = []
    for src, rel in [("skills", "digests/watchlist.json"),
                     ("n8n", "digests/workflows/watchlist.json")]:
        p = ROOT / rel
        if not p.exists():
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        for it in (data.get("items") or {}).values():
            tagged = dict(it)
            tagged["_status"] = "watch"
            out.append((src, tagged))
    return out


def test_every_watch_renders_detail():
    for source_key, item in _all_watch():
        text = _format_detail_watch(item, source_key)
        assert isinstance(text, str) and text, item.get("repo_full_name")
        assert len(text) < TELEGRAM_MSG_LIMIT


# --- Markdown safety on category labels -----------------------------------

def test_unknown_category_slug_escaped_in_line():
    """Real production bug: a watch item under n8n source carrying
    category='general_skill' (skill enum, not workflow enum) would render
    the bare slug into a Markdown message, with the unmatched underscore
    breaking Telegram's parser → 400 → silent no-op. _safe_cat_label
    must escape the fallback path."""
    from api.telegram import _format_item_line
    item = {
        "title": "owner/repo",
        "url": "https://github.com/owner/repo",
        "category": "general_skill",  # legacy skill slug in n8n source
    }
    line = _format_item_line(item, "n8n")
    # Underscore must be escaped — never appear unescaped in Markdown text
    assert "general_skill" not in line
    assert "general\\_skill" in line


def test_known_category_label_not_double_escaped():
    """Known workflow categories return human labels (no escape needed)."""
    from api.telegram import _format_item_line
    item = {
        "title": "owner/repo",
        "url": "https://github.com/owner/repo",
        "category": "marketing_workflow",
    }
    line = _format_item_line(item, "n8n")
    # Human label is "📈 Маркетинг" — emoji + word, no raw slug / underscore
    assert "📈 Маркетинг" in line
    assert "marketing_workflow" not in line


def test_safe_cat_label_handles_none_slug():
    """Missing category falls back to source default — must be label-mapped."""
    from api.telegram import _safe_cat_label
    out = _safe_cat_label("n8n", None)
    assert "_workflow" not in out  # must hit the label map
    assert "🔧" in out or "General" in out  # default is general_workflow → 🔧 General


def test_render_page_with_legacy_category_does_not_blow_up():
    """Wider smoke: a page rendering with an unknown-slug item should
    produce text containing only escaped underscores. End-to-end."""
    from api.telegram import _render_page, ALL_VIEW
    items = [{
        "title": "owner/repo",
        "url": "https://github.com/owner/repo",
        "category": "general_skill",
    }]
    text, _kb = _render_page(items, page=0, title="Test", source_key="n8n", nav_token="list")
    # No unescaped underscore (single \ in a raw string is the escape)
    import re
    unescaped = re.findall(r"(?<!\\)_", text)
    # _md_escape produces `\_` so unescaped count should be 0
    assert unescaped == [], f"Unescaped underscores found: {unescaped}"
