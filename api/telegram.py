"""Telegram bot webhook handler (Vercel Python serverless function).

Single-file interactive bot that reads recommendation JSON files from
raw.githubusercontent.com and serves them via Telegram commands and inline
keyboards. Stateless — no DB inside the function, 60s in-process cache.

Supports three data sources: Claude Skills, n8n Workflows, Make Workflows.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler
from typing import Any, Literal

import requests

# === Constants ===
# .strip() defends against trailing whitespace/newline in env vars
# (Vercel's textarea preserves a trailing \n on paste, which httpx
# rejects as "Illegal header value" before any network call).
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
# Optional — gates the "🤖 Объясни простыми словами" button on detail screens.
# Checked here (not via importing api.llm) so cold-start doesn't pay the
# anthropic import cost when the feature is disabled.
LLM_ENABLED = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
REPO = os.environ.get("BOT_REPO", "Libertad-Harbour-LLC/demo-repository").strip()
BRANCH = os.environ.get("BOT_BRANCH", "main").strip()
CACHE_TTL_SECONDS = 60

# Allow-list of Telegram user IDs that may interact with this bot.
# Override at deploy time with BOT_ADMIN_IDS="111,222"; the defaults below
# match the two admins who receive daily digests in the linked chat.
# Anyone outside the list gets a single "private bot" reply and no
# further response — Share deep-links also dead-end here.
_DEFAULT_ADMIN_IDS = {481077485, 576554290}


def _parse_admin_ids(raw: str) -> set[int]:
    out: set[int] = set()
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.add(int(tok))
        except ValueError:
            continue
    return out


_admin_env = _parse_admin_ids(os.environ.get("BOT_ADMIN_IDS", ""))
ADMIN_IDS: set[int] = _admin_env or _DEFAULT_ADMIN_IDS
PAGE_SIZE = 5  # items per page

# Source registry — see CONTEXT.md for the term definition.
@dataclass(frozen=True, eq=False)
class Source:
    """A logical data namespace served by the bot.

    Field types are enforced at construction (typed_dict-free). Adding a new
    Source = construct one instance below; no string-key drift. ``eq=False``
    skips auto-__hash__ (categories is a dict, so default hashing would fail);
    Source identity in practice is the SOURCES dict key.
    """
    key: str
    label: str        # button text shown on reply_keyboard + top picker
    header: str       # screen title
    url: str          # public recommended.json
    watchlist_url: str  # public watchlist.json
    categories: dict[str, str]  # category slug → display label
    default_category: str
    tool_filter: str | None  # None for skills; "n8n" / "make" for workflows


_SKILLS_CATS = {
    "marketing_skill": "📈 Marketing",
    "vibe_coding_skill": "💻 Vibe coding",
    "ai_content_skill": "🎨 AI content",
    "general_skill": "🔧 General",
}
_WORKFLOW_CATS = {
    "marketing_workflow": "📈 Marketing",
    "sales_workflow": "💰 Sales",
    "data_workflow": "📊 Data",
    "devops_workflow": "🛠 DevOps",
    "content_workflow": "🎨 Content",
    "general_workflow": "🔧 General",
}

SOURCES: dict[str, Source] = {
    "skills": Source(
        key="skills",
        label="📚 Claude Skills",
        header="Claude Skills",
        url=f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/digests/recommended.json",
        watchlist_url=f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/digests/watchlist.json",
        categories=_SKILLS_CATS,
        default_category="general_skill",
        tool_filter=None,
    ),
    "n8n": Source(
        key="n8n",
        label="⚙️ N8N Workflows",
        header="N8N Workflows",
        url=f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/digests/workflows/recommended.json",
        watchlist_url=f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/digests/workflows/watchlist.json",
        categories=_WORKFLOW_CATS,
        default_category="general_workflow",
        tool_filter="n8n",
    ),
    "make": Source(
        key="make",
        label="🧩 Make Workflows",
        header="Make Workflows",
        url=f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/digests/workflows/recommended.json",
        watchlist_url=f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/digests/workflows/watchlist.json",
        categories=_WORKFLOW_CATS,
        default_category="general_workflow",
        tool_filter="make",
    ),
}

VALID_SOURCES = set(SOURCES.keys())

# === In-process cache (keyed by URL) ===
_cache: dict[str, tuple[float, dict]] = {}


def _fetch_url(url: str, empty: dict) -> dict:
    """GET a JSON URL with a short in-process cache. Returns ``empty`` on miss."""
    now = time.time()
    cached = _cache.get(url)
    if cached is not None and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
        else:
            data = dict(empty)
    except Exception:
        data = cached[1] if cached is not None else dict(empty)
    _cache[url] = (now, data)
    return data


def _fetch(source_key: str) -> dict:
    """Fetch the recommended-skills DB for a source."""
    if source_key not in SOURCES:
        return {"skills": {}}
    return _fetch_url(SOURCES[source_key].url, {"skills": {}})


def _fetch_watchlist(source_key: str) -> dict:
    """Fetch the watchlist DB for a source (separate file, separate schema)."""
    if source_key not in SOURCES:
        return {"items": {}}
    url = SOURCES[source_key].watchlist_url
    if not url:
        return {"items": {}}
    return _fetch_url(url, {"items": {}})


# === Structured logging ===
# One JSON line per event to stderr. Vercel function logs are searchable
# with `grep | jq` after the fact; keeps the wire format machine-readable
# without bringing in an external metrics sink. Always best-effort —
# logging must never raise into the webhook.
def log_event(event: str, **fields: Any) -> None:
    try:
        record = {"event": event, "ts": time.time(), **fields}
        print(json.dumps(record, ensure_ascii=False, default=str), file=sys.stderr)
    except Exception:
        pass


# === Telegram API helpers ===
def _tg(method: str, **payload) -> dict:
    if not BOT_TOKEN:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN not set"}
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        resp = requests.post(url, json=payload, timeout=10)
        return resp.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _reply_keyboard() -> dict:
    """Persistent reply keyboard with the 3 source buttons + menu/help.

    Telegram only allows one `reply_markup` per sendMessage call. We attach
    this reply_keyboard only on messages that do NOT carry an inline_keyboard
    (i.e. menu-like messages). For messages with inline_keyboard, Telegram's
    client keeps the most recently set reply_keyboard visible automatically.
    """
    return {
        "keyboard": [
            [
                {"text": "📚 Claude Skills"},
                {"text": "⚙️ N8N Workflows"},
                {"text": "🧩 Make Workflows"},
            ],
            [
                {"text": "📋 Меню"},
                {"text": "ℹ️ Помощь"},
            ],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def _send_message(
    chat_id: int,
    text: str,
    reply_markup: dict | None = None,
    reply_keyboard: dict | None = None,
) -> dict:
    """Send a Telegram message.

    `reply_markup` (typically an inline_keyboard) takes precedence — Telegram
    accepts only one reply_markup per message. If only `reply_keyboard` is
    provided, it is used as reply_markup. If neither is provided, no markup.
    """
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    elif reply_keyboard is not None:
        payload["reply_markup"] = reply_keyboard
    return _tg("sendMessage", **payload)


def _edit_message(
    chat_id: int, message_id: int, text: str, reply_markup: dict | None = None
) -> dict:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return _tg("editMessageText", **payload)


def _answer_callback(callback_id: str, text: str = "") -> dict:
    payload: dict[str, Any] = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    return _tg("answerCallbackQuery", **payload)


# === Formatting ===
def _md_escape(text: str) -> str:
    # Legacy Markdown: escape chars Telegram's parser chokes on inside link text / bold.
    return (
        text.replace("_", "\\_")
        .replace("*", "\\*")
        .replace("[", "\\[")
        .replace("`", "\\`")
    )


def _format_item_line(item: dict, source_key: str) -> str:
    name = _md_escape(item.get("title") or item.get("repo_full_name", "?"))
    url = item.get("url", "")
    tool = item.get("tool")
    tool_prefix = ""
    if isinstance(tool, str) and tool:
        tool_prefix = f"[{tool}] "
    status_prefix = "👀 " if item.get("_status") == "watch" else ""

    # Workflows have a `workflows` array; skills have `skills_in_repo` (or `skills`).
    sub_items = (
        item.get("workflows")
        or item.get("skills_in_repo")
        or item.get("skills")
        or []
    )
    sub_label = "workflows" if item.get("workflows") else "skills"
    if isinstance(sub_items, list) and sub_items:
        names: list[str] = []
        for s in sub_items[:3]:
            if isinstance(s, str):
                names.append(s)
            elif isinstance(s, dict):
                names.append(s.get("name", ""))
        names = [n for n in names if n]
        more = "…" if len(sub_items) > 3 else ""
        if names:
            sub_str = f" ({len(sub_items)} {sub_label}: {', '.join(names)}{more})"
        else:
            sub_str = f" ({len(sub_items)} {sub_label})"
    else:
        sub_str = ""

    stars = item.get("stars")
    stars_str = f" ⭐ {stars}" if isinstance(stars, int) else ""
    score = item.get("final_score")
    score_str = (
        f" • score {score}"
        if isinstance(score, (int, float)) and not isinstance(score, bool)
        else ""
    )
    cat = item.get("category", "")
    cat_labels = SOURCES[source_key].categories
    cat_str = f" • {cat_labels.get(cat, cat)}" if cat else ""
    # No leading bullet — caller prefixes with its own marker ("N." for paginated lists).
    return f"{status_prefix}{tool_prefix}[{name}]({url}){sub_str}{stars_str}{score_str}{cat_str}"


# === Items ===
# A sorted, tool-filtered list of recommended + watchlist Items for one Source.
# See CONTEXT.md for "Item", "Status", "Source".
@dataclass(frozen=True, eq=False)
class Items:
    """All Items the bot can show for one Source, after dedupe + tool filter + sort.

    Construct via ``Items.load(source_key)`` — handles both file reads (recommended
    + watchlist), Status tagging, dedupe by URL (recommended wins), tool filter,
    and stable sort. Filters return a new Items; the type is immutable in spirit
    (``eq=False`` skips auto-hash; the underlying list isn't hashable).

    Behaves as a sequence: ``len(items)``, ``items[i]``, ``items[a:b]``,
    ``for it in items``.
    """
    _items: list[dict]
    source_key: str

    @classmethod
    def load(cls, source_key: str) -> "Items":
        rec_items = list((_fetch(source_key).get("skills") or {}).values())
        rec_urls = {i.get("url") for i in rec_items if i.get("url")}
        watch_items = [
            cls._tag_watch(e)
            for e in (_fetch_watchlist(source_key).get("items") or {}).values()
            if isinstance(e, dict) and e.get("url") not in rec_urls
        ]
        merged = cls._apply_tool_filter(rec_items + watch_items, source_key)
        merged.sort(
            key=lambda s: (s.get("first_recommended", ""), s.get("title", "")),
            reverse=True,
        )
        return cls(_items=merged, source_key=source_key)

    @staticmethod
    def _tag_watch(entry: dict) -> dict:
        """Map a watchlist entry into the recommended-shape vocabulary the bot expects."""
        out = dict(entry)
        out["_status"] = "watch"
        if "first_recommended" not in out and "added_date" in out:
            out["first_recommended"] = out["added_date"]
        return out

    @staticmethod
    def _apply_tool_filter(items: list[dict], source_key: str) -> list[dict]:
        """Workflows-side tool filter. Watch entries from older pipeline runs
        lack a ``tool`` field — surface those only under the "n8n" bucket.
        """
        tool_filter = SOURCES[source_key].tool_filter
        if tool_filter is None:
            return items

        def matches(i: dict) -> bool:
            t = i.get("tool")
            if t == tool_filter:
                return True
            return i.get("_status") == "watch" and not t and tool_filter == "n8n"

        return [i for i in items if matches(i)]

    def filter_by_category(self, cat: str) -> "Items":
        default_cat = SOURCES[self.source_key].default_category
        return Items(
            _items=[s for s in self._items if s.get("category", default_cat) == cat],
            source_key=self.source_key,
        )

    def filter_by_month(self, ym: str) -> "Items":
        return Items(
            _items=[s for s in self._items if (s.get("first_recommended") or "")[:7] == ym],
            source_key=self.source_key,
        )

    def filter_for_view(self, view: "View") -> "Items":
        if view.kind == "category":
            return self.filter_by_category(view.arg)
        if view.kind == "month":
            return self.filter_by_month(view.arg)
        return self

    def find_by_url_id(self, uid: str) -> dict | None:
        """Look up a single Item by its short URL hash. None if not found."""
        for item in self._items:
            if _url_id(item.get("url") or "") == uid:
                return item
        return None

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):
        return iter(self._items)

    def __getitem__(self, idx):
        return self._items[idx]


def _url_id(url: str) -> str:
    """Short stable identifier for an Item URL — fits in Telegram's 64-byte
    callback_data limit even when repo_full_name is too long. 8 hex chars
    from sha1; collision space is ~16M which is plenty for our DB scale.
    """
    if not url:
        return ""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]


# === Views ===
# A View selects what to show on a paginated screen. `nav_token` is the
# callback-data suffix used for pagination (`src:<source>:<nav_token>:<page>`)
# and MUST stay byte-identical across releases — inline keyboards live in user
# chat history indefinitely and fire the exact string they were built with.
ViewKind = Literal["all", "category", "month"]


@dataclass(frozen=True)
class View:
    kind: ViewKind
    nav_token: str
    arg: str | None = None  # category slug for "category"; YYYY-MM for "month"


ALL_VIEW = View(kind="all", nav_token="list")


def category_view(cat: str) -> View:
    return View(kind="category", nav_token=f"cat:{cat}", arg=cat)


def month_view(ym: str) -> View:
    return View(kind="month", nav_token=f"month:{ym}", arg=ym)


def _format_detail_recommended(item: dict, source_key: str) -> str:
    """Multi-section Markdown body for the item-detail screen (recommended item)."""
    title = _md_escape(item.get("title") or item.get("repo_full_name") or "?")
    url = item.get("url") or ""
    cat_labels = SOURCES[source_key].categories
    cat = item.get("category") or ""
    cat_label = cat_labels.get(cat, cat or SOURCES[source_key].default_category)

    lines = [f"📚 *{title}*", ""]
    lines.append(f"🏷 Категория: {cat_label}")
    if first := item.get("first_recommended"):
        lines.append(f"📅 Добавлен: {first}")

    meta_parts: list[str] = []
    stars = item.get("stars")
    if isinstance(stars, int):
        meta_parts.append(f"⭐ {stars}")
    score = item.get("final_score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        meta_parts.append(f"📊 score {score}")
    if conf := item.get("confidence"):
        meta_parts.append(f"confidence {conf}")
    if meta_parts:
        lines.append(" • ".join(meta_parts))

    if desc := item.get("description"):
        lines.append("")
        lines.append("📝 " + _md_escape(desc))

    skills_in_repo = item.get("skills_in_repo") or []
    if skills_in_repo:
        lines.append("")
        n = len(skills_in_repo)
        label = "workflows" if item.get("tool") else "skills"
        lines.append(f"📦 {label.capitalize()} внутри ({n}):")
        for s in skills_in_repo[:15]:
            lines.append(f"• {_md_escape(str(s))}")
        if n > 15:
            lines.append(f"… ещё {n - 15}")

    test_steps = item.get("test_steps") or []
    if test_steps:
        lines.append("")
        lines.append("🧪 Шаги тестирования:")
        for i, step in enumerate(test_steps, 1):
            lines.append(f"{i}. {_md_escape(str(step))}")

    if metric := item.get("metric"):
        lines.append("")
        lines.append(f"📈 Метрика: {_md_escape(metric)}")

    if url:
        lines.append("")
        lines.append(f"🔗 [Открыть в GitHub]({url})")

    return "\n".join(lines)


def _format_detail_watch(item: dict, source_key: str) -> str:
    """Multi-section Markdown body for a watch item."""
    title = _md_escape(item.get("title") or item.get("repo_full_name") or "?")
    url = item.get("url") or ""
    cat_labels = SOURCES[source_key].categories
    cat = item.get("category") or ""
    cat_label = cat_labels.get(cat, cat or SOURCES[source_key].default_category)

    lines = [f"👀 *{title}*", ""]
    lines.append("📍 Статус: На наблюдении")
    lines.append(f"🏷 Категория: {cat_label}")
    if added := item.get("added_date"):
        suffix = f" (истекает {item['expires_at']})" if item.get("expires_at") else ""
        lines.append(f"📅 Добавлен: {added}{suffix}")
    if last := item.get("last_checked"):
        lines.append(f"📍 Последняя проверка: {last}")

    if desc := item.get("description"):
        lines.append("")
        lines.append("📝 " + _md_escape(desc))

    if why := item.get("why_interesting"):
        lines.append("")
        lines.append("💡 Почему интересно:")
        lines.append(_md_escape(why))

    if signal := item.get("signal_to_wait"):
        lines.append("")
        lines.append("🎯 Сигнал ожидания:")
        lines.append(_md_escape(signal))

    baseline = item.get("metric_baseline") or {}
    base_lines: list[str] = []
    if isinstance(baseline.get("stars"), int):
        base_lines.append(f"• ⭐ stars: {baseline['stars']}")
    if isinstance(baseline.get("skills_count"), int):
        base_lines.append(f"• 📦 skills: {baseline['skills_count']}")
    if isinstance(baseline.get("cross_source_count"), int):
        base_lines.append(f"• 🔗 sources: {baseline['cross_source_count']}")
    if base_lines:
        lines.append("")
        lines.append("📊 Baseline-метрики:")
        lines.extend(base_lines)

    if url:
        lines.append("")
        lines.append(f"🔗 [Открыть в GitHub]({url})")

    return "\n".join(lines)


def _title_for_view(view: View, source_key: str) -> str:
    header = SOURCES[source_key].header
    if view.kind == "category":
        cat_labels = SOURCES[source_key].categories
        label = cat_labels.get(
            view.arg, view.arg or SOURCES[source_key].default_category
        )
        return f"{header} — {label}"
    if view.kind == "month":
        return f"{header} — 📅 {view.arg}"
    return f"Все — {header}"


# === Page rendering ===
def _render_page(
    items: list[dict],
    page: int,
    title: str,
    source_key: str,
    nav_token: str,
) -> tuple[str, dict]:
    """Render a single page of items.

    `nav_token` is the callback suffix for pagination, e.g.
    "list", "cat:marketing_skill", "month:2026-05". Full callback_data
    is `src:<source_key>:<nav_token>:<page>`.
    """
    total = len(items)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    chunk = items[start:end]

    if not chunk:
        kb = {
            "inline_keyboard": [
                [{"text": "« Меню", "callback_data": f"src:{source_key}:menu"}],
                [{"text": "« Источник", "callback_data": "menu"}],
            ]
        }
        return (f"*{title}*\n\nПусто.", kb)

    lines = [f"*{title}* — стр. {page+1}/{total_pages} ({total} всего)\n"]
    for i, s in enumerate(chunk, 1):
        # Render with a numeric prefix matching the [📋 N] button below.
        lines.append(f"{i}. {_format_item_line(s, source_key)}")

    # Detail-screen entry: one button per item on this page. `_url_id` keeps
    # callback_data short and stable even for long repo_full_name values.
    detail_row = [
        {
            "text": f"📋 {i}",
            "callback_data": f"src:{source_key}:item:{_url_id(s.get('url') or '')}",
        }
        for i, s in enumerate(chunk, 1)
    ]

    nav: list[dict] = []
    if page > 0:
        nav.append(
            {
                "text": "← Назад",
                "callback_data": f"src:{source_key}:{nav_token}:{page-1}",
            }
        )
    if end < total:
        nav.append(
            {
                "text": "Дальше →",
                "callback_data": f"src:{source_key}:{nav_token}:{page+1}",
            }
        )
    kb_rows: list[list[dict]] = [detail_row]
    if nav:
        kb_rows.append(nav)
    kb_rows.append([{"text": "« Меню", "callback_data": f"src:{source_key}:menu"}])
    kb_rows.append([{"text": "« Источник", "callback_data": "menu"}])
    return ("\n".join(lines), {"inline_keyboard": kb_rows})


# === Screens ===
# A Screen is a (text, inline_keyboard_or_None) tuple. Pure rendering: no
# transport, no side effects. Sent or edited via deliver().
Screen = tuple[str, dict | None]


def screen_top_menu() -> Screen:
    text = "*Trendwatch — базы рекомендаций*\n\nВыбери источник:"
    kb = {
        "inline_keyboard": [
            [{"text": SOURCES["skills"].label, "callback_data": "src:skills:menu"}],
            [{"text": SOURCES["n8n"].label, "callback_data": "src:n8n:menu"}],
            [{"text": SOURCES["make"].label, "callback_data": "src:make:menu"}],
        ]
    }
    return text, kb


def screen_source_menu(source_key: str) -> Screen:
    text = f"*{SOURCES[source_key].header}*\n\nВыбери что показать:"
    kb = {
        "inline_keyboard": [
            [{"text": "📚 Весь список", "callback_data": f"src:{source_key}:list:0"}],
            [{"text": "🏷 По категории", "callback_data": f"src:{source_key}:categories"}],
            [{"text": "📅 По месяцу", "callback_data": f"src:{source_key}:months"}],
            [{"text": "🎲 Случайный", "callback_data": f"src:{source_key}:random"}],
            [{"text": "« Источник", "callback_data": "menu"}],
        ]
    }
    return text, kb


def screen_categories(source_key: str) -> Screen:
    items = Items.load(source_key)
    default_cat = SOURCES[source_key].default_category
    cat_labels: dict[str, str] = SOURCES[source_key].categories
    cat_counts: dict[str, int] = {}
    for s in items:
        c = s.get("category", default_cat)
        cat_counts[c] = cat_counts.get(c, 0) + 1
    text = f"*Категории {SOURCES[source_key].header}:*\n\n"
    rows: list[list[dict]] = []
    for cat, label in cat_labels.items():
        n = cat_counts.get(cat, 0)
        text += f"{label} — {n}\n"
        if n > 0:
            rows.append([{"text": f"{label} ({n})", "callback_data": f"src:{source_key}:cat:{cat}:0"}])
    # Include any unknown categories that exist in data but not in labels
    for cat, n in cat_counts.items():
        if cat not in cat_labels and n > 0:
            label = cat or default_cat
            text += f"{label} — {n}\n"
            rows.append([{"text": f"{label} ({n})", "callback_data": f"src:{source_key}:cat:{cat}:0"}])
    rows.append([{"text": "« Меню", "callback_data": f"src:{source_key}:menu"}])
    rows.append([{"text": "« Источник", "callback_data": "menu"}])
    return text, {"inline_keyboard": rows}


def screen_months(source_key: str) -> Screen:
    items = Items.load(source_key)
    month_counts: dict[str, int] = {}
    for s in items:
        date = s.get("first_recommended", "") or ""
        if len(date) >= 7:
            month_counts[date[:7]] = month_counts.get(date[:7], 0) + 1
    if not month_counts:
        return (
            f"*{SOURCES[source_key].header}*\n\nПусто.",
            {
                "inline_keyboard": [
                    [{"text": "« Меню", "callback_data": f"src:{source_key}:menu"}],
                    [{"text": "« Источник", "callback_data": "menu"}],
                ]
            },
        )
    rows: list[list[dict]] = []
    text = f"*{SOURCES[source_key].header} — по месяцам:*\n\n"
    for ym in sorted(month_counts.keys(), reverse=True):
        n = month_counts[ym]
        text += f"📅 {ym} — {n}\n"
        rows.append([{"text": f"{ym} ({n})", "callback_data": f"src:{source_key}:month:{ym}:0"}])
    rows.append([{"text": "« Меню", "callback_data": f"src:{source_key}:menu"}])
    rows.append([{"text": "« Источник", "callback_data": "menu"}])
    return text, {"inline_keyboard": rows}


def screen_page(source_key: str, view: View, page: int) -> Screen:
    """Render a paginated bot screen for ``view`` of ``source_key``."""
    items = Items.load(source_key).filter_for_view(view)
    return _render_page(
        items, page, _title_for_view(view, source_key), source_key, view.nav_token
    )


def screen_item(source_key: str, uid: str) -> Screen:
    """Detail screen for one Item, looked up by short URL hash.

    Back navigation: ``« К списку`` jumps to the first page of the Source's
    ``all`` view — the previous filter/page context isn't preserved in the
    callback chain (would inflate callback_data past Telegram's 64-byte limit).
    """
    item = Items.load(source_key).find_by_url_id(uid)
    if item is None:
        text = "Айтем не найден — возможно, удалён из базы."
    elif item.get("_status") == "watch":
        text = _format_detail_watch(item, source_key)
    else:
        text = _format_detail_recommended(item, source_key)

    rows: list[list[dict]] = []
    if LLM_ENABLED and item is not None:
        rows.append([{
            "text": "🤖 Объясни простыми словами",
            "callback_data": f"src:{source_key}:explain:{uid}",
        }])
    if item is not None:
        rows.append([
            {"text": "📋 Поставить", "callback_data": f"src:{source_key}:setup:{uid}"},
            {"text": "🎯 Похожие", "callback_data": f"src:{source_key}:similar:{uid}"},
        ])
        rows.append([{"text": "🔗 Поделиться", "callback_data": f"src:{source_key}:share:{uid}"}])
    rows.append([{"text": "« К списку", "callback_data": f"src:{source_key}:list:0"}])
    rows.append([{"text": "« Меню источника", "callback_data": f"src:{source_key}:menu"}])
    rows.append([{"text": "« Источник", "callback_data": "menu"}])
    kb = {"inline_keyboard": rows}
    return text, kb


SEARCH_RESULT_LIMIT = 10


def screen_random(source_key: str) -> Screen:
    """Pick one Item from the source uniformly at random; render its detail.

    Empty source → friendly message + source-menu back button. The detail
    screen for the picked Item already provides full navigation.
    """
    items = Items.load(source_key)
    if len(items) == 0:
        kb = {"inline_keyboard": [
            [{"text": "« Меню источника", "callback_data": f"src:{source_key}:menu"}],
        ]}
        return (f"*{SOURCES[source_key].header}*\n\nПусто.", kb)
    chosen = random.choice(list(items))
    return screen_item(source_key, _url_id(chosen.get("url") or ""))


def screen_search(query: str) -> Screen:
    """Substring search across all Sources. Caps at SEARCH_RESULT_LIMIT.

    Matches case-insensitive against title, repo_full_name, description,
    and skills_in_repo entries. Results are listed with a source-tag prefix
    and one [📋 N] detail button per result. No pagination — refine the
    query to narrow.
    """
    q = (query or "").strip().lower()
    if not q:
        return (
            "Пустой запрос. Пример: `/search seo`",
            {"inline_keyboard": [[{"text": "« Меню", "callback_data": "menu"}]]},
        )

    hits: list[tuple[str, dict]] = []  # (source_key, item)
    for source_key in SOURCES:
        for it in Items.load(source_key):
            haystack = " ".join([
                str(it.get("title") or ""),
                str(it.get("repo_full_name") or ""),
                str(it.get("description") or ""),
                " ".join(str(s) for s in (it.get("skills_in_repo") or [])),
            ]).lower()
            if q in haystack:
                hits.append((source_key, it))

    if not hits:
        return (
            f"По запросу *{_md_escape(query)}* ничего не нашлось.",
            {"inline_keyboard": [[{"text": "« Меню", "callback_data": "menu"}]]},
        )

    total = len(hits)
    shown = hits[:SEARCH_RESULT_LIMIT]
    source_emoji = {"skills": "📚", "n8n": "⚙️", "make": "🧩"}

    head = f"🔎 *Поиск:* `{_md_escape(query)}` — найдено {total}"
    if total > SEARCH_RESULT_LIMIT:
        head += f", показаны первые {SEARCH_RESULT_LIMIT}"
    lines = [head, ""]
    detail_row: list[dict] = []
    for i, (source_key, it) in enumerate(shown, 1):
        tag = source_emoji.get(source_key, "•")
        lines.append(f"{i}. {tag} {_format_item_line(it, source_key)}")
        detail_row.append({
            "text": f"📋 {i}",
            "callback_data": f"src:{source_key}:item:{_url_id(it.get('url') or '')}",
        })

    kb = {"inline_keyboard": [detail_row, [{"text": "« Меню", "callback_data": "menu"}]]}
    return ("\n".join(lines), kb)


def screen_stats() -> Screen:
    """Counts per Source, last update date, watch totals. Pure read of JSONs."""
    lines = ["📊 *Состояние баз*", ""]
    source_emoji = {"skills": "📚", "n8n": "⚙️", "make": "🧩"}
    for source_key, source in SOURCES.items():
        rec = list(_fetch(source_key).get("skills", {}).values())
        watch = list(_fetch_watchlist(source_key).get("items", {}).values())
        # Tool filter is applied for fairness with what the user sees in /list.
        rec_in_view = Items._apply_tool_filter(rec, source_key)
        watch_in_view = Items._apply_tool_filter(watch, source_key)
        last = max(
            (it.get("first_recommended", "") for it in rec_in_view if it.get("first_recommended")),
            default="—",
        )
        tag = source_emoji.get(source_key, "•")
        lines.append(
            f"{tag} *{source.header}*: {len(rec_in_view)} рекомендованных, "
            f"{len(watch_in_view)} 👀 на наблюдении\n  последнее: {last}"
        )

    kb = {"inline_keyboard": [[{"text": "« Меню", "callback_data": "menu"}]]}
    return ("\n".join(lines), kb)


def pick_random_anywhere() -> tuple[str, dict] | None:
    """Pick a random recommended Item from any Source. None if all empty."""
    pool: list[tuple[str, dict]] = []
    for source_key in SOURCES:
        for it in Items.load(source_key):
            pool.append((source_key, it))
    if not pool:
        return None
    return random.choice(pool)


def find_item_anywhere(uid: str) -> tuple[str, dict] | None:
    """Locate an Item by url_id across all Sources (for deep links)."""
    for source_key in SOURCES:
        it = Items.load(source_key).find_by_url_id(uid)
        if it is not None:
            return (source_key, it)
    return None


_bot_username_cache: list[str | None] = [None]  # list for mutability across calls


def bot_username() -> str | None:
    """Resolve the bot's @username (without the @).

    Order: BOT_USERNAME env var → cached getMe result → fresh getMe call.
    None only if env is unset, getMe fails, and we have no cache. The
    in-process cache persists across invocations of the same warm Vercel
    function instance; cold starts pay one extra getMe.
    """
    env_val = os.environ.get("BOT_USERNAME", "").strip()
    if env_val:
        return env_val
    if _bot_username_cache[0]:
        return _bot_username_cache[0]
    r = _tg("getMe")
    if r.get("ok"):
        u = ((r.get("result") or {}).get("username") or "").strip()
        if u:
            _bot_username_cache[0] = u
            return u
    return None


def _repo_clone_url(item_url: str) -> str:
    """Strip /tree/... so the URL becomes a clone-ready repo root."""
    return re.sub(r"/tree/.*$", "", item_url or "")


def screen_share(source_key: str, uid: str) -> Screen:
    """Render a copy-pasteable t.me deep-link for one Item."""
    username = bot_username()
    if not username:
        text = (
            "🔗 *Поделиться*\n\n"
            "Не удалось определить @username бота (getMe вернул ошибку). "
            "Задай переменную `BOT_USERNAME` в Vercel env vars."
        )
    else:
        link = f"https://t.me/{username}?start=item_{uid}"
        text = (
            "🔗 *Поделиться этим айтемом*\n\n"
            "Скопируй и отправь:\n"
            f"`{link}`\n\n"
            "У получателя бот сразу откроет детальный экран."
        )
    kb = {"inline_keyboard": [
        [{"text": "« Назад к айтему", "callback_data": f"src:{source_key}:item:{uid}"}],
    ]}
    return text, kb


def screen_setup(source_key: str, uid: str) -> Screen:
    """Render an install snippet appropriate for the Source's tool."""
    item = Items.load(source_key).find_by_url_id(uid)
    if item is None:
        return ("Айтем не найден.", {"inline_keyboard": [
            [{"text": "« К списку", "callback_data": f"src:{source_key}:list:0"}],
        ]})

    url = item.get("url") or ""
    if source_key == "skills":
        clone = _repo_clone_url(url)
        if clone and not clone.endswith(".git"):
            clone_git = f"{clone}.git"
        else:
            clone_git = clone or "<url>"
        # Inferring repo dir name from the URL last path segment
        repo_dir = clone.rstrip("/").split("/")[-1] if clone else "<repo>"
        text = (
            "📋 *Как поставить skill*\n\n"
            "```\n"
            f"git clone {clone_git}\n"
            f"mkdir -p ~/.claude/skills\n"
            f"cp -r {repo_dir}/.claude/skills/* ~/.claude/skills/\n"
            "```\n"
            "После этого Claude Code сам подхватит SKILL.md из этих папок."
        )
    else:  # n8n / make workflows
        json_url = item.get("json_url") or url
        tool = item.get("tool") or source_key
        target = "n8n" if tool == "n8n" else "Make"
        text = (
            f"📋 *Как поставить workflow ({target})*\n\n"
            f"1. Скачай JSON:\n`{json_url}`\n"
            f"2. В {target} → Import → выбери файл\n"
            "3. Настрой credentials/переменные окружения\n"
            "4. Запусти тестовый прогон по `test_steps` со страницы айтема"
        )

    kb = {"inline_keyboard": [
        [{"text": "« Назад к айтему", "callback_data": f"src:{source_key}:item:{uid}"}],
    ]}
    return text, kb


SIMILAR_LIMIT = 5


def screen_similar(source_key: str, uid: str) -> Screen:
    """List up to SIMILAR_LIMIT same-category Items (excluding the current one)."""
    items = Items.load(source_key)
    current = items.find_by_url_id(uid)
    if current is None:
        return ("Айтем не найден.", {"inline_keyboard": [
            [{"text": "« К списку", "callback_data": f"src:{source_key}:list:0"}],
        ]})

    cat = current.get("category") or SOURCES[source_key].default_category
    cat_label = SOURCES[source_key].categories.get(cat, cat)
    siblings = [
        s for s in items.filter_by_category(cat)
        if _url_id(s.get("url") or "") != uid
    ][:SIMILAR_LIMIT]

    if not siblings:
        text = f"🎯 *Похожие в категории {cat_label}*\n\nБольше ничего нет."
        kb = {"inline_keyboard": [
            [{"text": "« Назад к айтему", "callback_data": f"src:{source_key}:item:{uid}"}],
        ]}
        return text, kb

    lines = [f"🎯 *Похожие в категории {cat_label}*", ""]
    detail_row: list[dict] = []
    for i, s in enumerate(siblings, 1):
        lines.append(f"{i}. {_format_item_line(s, source_key)}")
        detail_row.append({
            "text": f"📋 {i}",
            "callback_data": f"src:{source_key}:item:{_url_id(s.get('url') or '')}",
        })

    kb = {"inline_keyboard": [
        detail_row,
        [{"text": "« Назад к айтему", "callback_data": f"src:{source_key}:item:{uid}"}],
    ]}
    return "\n".join(lines), kb


WHATSNEW_WINDOW_DAYS = 2


def screen_whatsnew() -> Screen:
    """Cross-source list of Items added in the last WHATSNEW_WINDOW_DAYS days.

    Compares against ``first_recommended`` (UTC date string). Newest first.
    """
    cutoff = (date.today() - timedelta(days=WHATSNEW_WINDOW_DAYS)).isoformat()
    hits: list[tuple[str, dict]] = []
    for source_key in SOURCES:
        for it in Items.load(source_key):
            if (it.get("first_recommended") or "") >= cutoff:
                hits.append((source_key, it))

    if not hits:
        return (
            f"📰 За последние {WHATSNEW_WINDOW_DAYS} дня ничего нового в базах.",
            {"inline_keyboard": [[{"text": "« Меню", "callback_data": "menu"}]]},
        )

    hits.sort(key=lambda h: (h[1].get("first_recommended", ""), h[1].get("title", "")), reverse=True)
    source_emoji = {"skills": "📚", "n8n": "⚙️", "make": "🧩"}

    lines = [f"📰 *Что нового за {WHATSNEW_WINDOW_DAYS} дня* — {len(hits)}", ""]
    detail_row: list[dict] = []
    for i, (source_key, it) in enumerate(hits[:10], 1):
        tag = source_emoji.get(source_key, "•")
        lines.append(f"{i}. {tag} {_format_item_line(it, source_key)}")
        detail_row.append({
            "text": f"📋 {i}",
            "callback_data": f"src:{source_key}:item:{_url_id(it.get('url') or '')}",
        })

    kb = {"inline_keyboard": [detail_row, [{"text": "« Меню", "callback_data": "menu"}]]}
    return ("\n".join(lines), kb)


# === Transport adapter ===
def deliver(
    chat_id: int,
    screen: Screen,
    *,
    edit_message_id: int | None = None,
    reply_keyboard: dict | None = None,
) -> dict:
    """Send ``screen`` as a new message, or edit ``edit_message_id`` in place.

    Telegram limitation: edited messages cannot change the persistent
    reply_keyboard. ``reply_keyboard`` is honoured only on the send path.
    """
    text, inline = screen
    if edit_message_id is not None:
        return _edit_message(chat_id, edit_message_id, text, inline)
    return _send_message(
        chat_id, text, reply_markup=inline, reply_keyboard=reply_keyboard
    )


# === Static help text ===
HELP_TEXT = (
    "*Trendwatch — навигатор по базе*\n"
    "\n"
    "Что это: я храню рекомендованные Claude Skills и готовые n8n / Make workflows.\n"
    "Базы пополняются автоматически каждый день.\n"
    "\n"
    "Кнопки внизу чата:\n"
    "📚 Claude Skills — база рекомендованных Claude Skills (с категориями)\n"
    "⚙️ N8N Workflows — готовые n8n workflows для импорта\n"
    "🧩 Make Workflows — готовые Make blueprints\n"
    "📋 Меню — главное меню (выбор источника)\n"
    "ℹ️ Помощь — это сообщение\n"
    "\n"
    "Команды:\n"
    "/start, /menu — главное меню\n"
    "/skills, /n8n, /make — открыть нужный источник\n"
    "/search <текст> — поиск по всем базам\n"
    "/random — случайная рекомендация\n"
    "/whatsnew — что добавилось за последние 2 дня\n"
    "/stats — счётчики по базам\n"
    "/list, /categories, /months — устаревший доступ к skills\n"
    "/help — это сообщение\n"
    "\n"
    "База обновляется через GitHub-репозиторий; в каждом дайджесте под пунктами есть прямые ссылки на источники."
)


# === Route ===
# A parsed callback_data string. See CONTEXT.md → "Route".
# Wire format is byte-stable across releases — inline keyboards live in user
# chat history indefinitely and fire whatever string was baked at send time.
RouteKind = Literal[
    "top_menu",     # bare "menu"
    "source_menu",  # src:<source>:menu
    "categories",   # src:<source>:categories
    "months",       # src:<source>:months
    "list",         # src:<source>:list[:<page>]
    "category",     # src:<source>:cat:<slug>[:<page>]
    "month",        # src:<source>:month:<ym>[:<page>]
    "item",         # src:<source>:item:<url_id>
    "explain",      # src:<source>:explain:<url_id>
    "random",       # src:<source>:random — pick & open a random Item
    "share",        # src:<source>:share:<url_id> — print t.me deep link
    "setup",        # src:<source>:setup:<url_id> — print install snippet
    "similar",      # src:<source>:similar:<url_id> — list same-category items
]


@dataclass(frozen=True)
class Route:
    """Parsed inline-button callback target.

    ``source_key`` is None only for ``top_menu``. ``arg`` carries the
    payload that depends on ``kind``: category slug, ``YYYY-MM`` month,
    or url_id. ``page`` defaults to 0 for non-paginated kinds.

    Construct via ``Route.parse(data)`` — never instantiate by hand from
    user input.
    """
    kind: RouteKind
    source_key: str | None
    arg: str | None = None
    page: int = 0

    @classmethod
    def parse(cls, data: str) -> "Route | None":
        if data == "menu":
            return cls(kind="top_menu", source_key=None)
        if not data.startswith("src:"):
            return None
        parts = data.split(":")
        if len(parts) < 3:
            return None
        source_key, action = parts[1], parts[2]
        if source_key not in VALID_SOURCES:
            return None

        if action in ("menu", "categories", "months", "random"):
            kind: RouteKind = "source_menu" if action == "menu" else action  # type: ignore[assignment]
            return cls(kind=kind, source_key=source_key)
        if action == "list":
            return cls(kind="list", source_key=source_key, page=_parse_page(parts, 3))
        if action == "cat" and len(parts) >= 4:
            return cls(
                kind="category", source_key=source_key,
                arg=parts[3], page=_parse_page(parts, 4),
            )
        if action == "month" and len(parts) >= 4:
            return cls(
                kind="month", source_key=source_key,
                arg=parts[3], page=_parse_page(parts, 4),
            )
        if action in ("item", "explain", "share", "setup", "similar") and len(parts) >= 4:
            return cls(kind=action, source_key=source_key, arg=parts[3])  # type: ignore[arg-type]
        return None


def _parse_page(parts: list[str], idx: int) -> int:
    """Parse a 0-based page index out of ``parts[idx]``, defaulting to 0."""
    if len(parts) <= idx:
        return 0
    try:
        return int(parts[idx])
    except ValueError:
        return 0


# === Inline-button callback routing ===
def handle_callback(update: dict) -> None:
    """Route a Telegram inline-keyboard tap to the right Screen.

    Parses ``callback_data`` into a typed :class:`Route`, then dispatches on
    ``route.kind``. All Screen-returning kinds end in ``show(screen)`` — a
    closure that binds chat_id and the message_id to edit. ``explain`` is
    the lone side-effect kind: it sends a NEW message rather than editing.
    """
    cb = update["callback_query"]
    chat_id = cb["message"]["chat"]["id"]
    msg_id = cb["message"]["message_id"]
    _answer_callback(cb["id"])

    raw = cb.get("data", "") or ""
    route = Route.parse(raw)
    if route is None:
        log_event("callback.unparsed", raw=raw[:80])
        return
    log_event(
        "callback",
        kind=route.kind, src=route.source_key,
        page=route.page, has_arg=bool(route.arg),
    )

    def show(screen: Screen) -> None:
        deliver(chat_id, screen, edit_message_id=msg_id)

    src = route.source_key
    if route.kind == "top_menu":
        show(screen_top_menu())
    elif route.kind == "source_menu":
        show(screen_source_menu(src))
    elif route.kind == "categories":
        show(screen_categories(src))
    elif route.kind == "months":
        show(screen_months(src))
    elif route.kind == "list":
        show(screen_page(src, ALL_VIEW, route.page))
    elif route.kind == "category":
        show(screen_page(src, category_view(route.arg), route.page))
    elif route.kind == "month":
        show(screen_page(src, month_view(route.arg), route.page))
    elif route.kind == "item":
        show(screen_item(src, route.arg))
    elif route.kind == "random":
        show(screen_random(src))
    elif route.kind == "share":
        show(screen_share(src, route.arg))
    elif route.kind == "setup":
        show(screen_setup(src, route.arg))
    elif route.kind == "similar":
        show(screen_similar(src, route.arg))
    elif route.kind == "explain":
        # Agentic feature: separate code path (sends a NEW message rather than
        # editing the detail screen so context stays visible above).
        handle_explain(chat_id, src, route.arg)


def handle_explain(chat_id: int, source_key: str, uid: str) -> None:
    """[🤖 Объясни простыми словами] agentic handler.

    Looks up the Item by url_id, calls the LLM, and sends the explanation as a
    NEW message (not an edit) so the detail screen stays visible above. Any
    failure path — missing key, network, Markdown parse rejection, even an
    unexpected exception in the LLM module — surfaces a visible message;
    the handler never silently no-ops.
    """
    started = time.time()
    try:
        # Lazy import — anthropic SDK shouldn't load on every callback cold-start,
        # only when this code path actually runs.
        from api.llm import _mask_secrets, explain_item

        item = Items.load(source_key).find_by_url_id(uid)
        if item is None:
            log_event("explain.not_found", src=source_key, uid=uid)
            _send_plain(chat_id, "Айтем не найден — возможно, удалён из базы.")
            return
        text, error = explain_item(item, source_key)
        elapsed_ms = int((time.time() - started) * 1000)
        if not text:
            log_event(
                "explain.fail", src=source_key, uid=uid,
                ms=elapsed_ms, error=(error or "unknown")[:200],
            )
            _send_plain(
                chat_id,
                _mask_secrets(
                    f"Не удалось получить объяснение.\nПричина: {error or 'неизвестна'}"
                ),
            )
            return
        log_event(
            "explain.ok", src=source_key, uid=uid,
            ms=elapsed_ms, chars=len(text),
        )
        # Successful explanations are plain prose; send without Markdown so
        # any stray * / _ / [ from the LLM output never trips Telegram's parser.
        _send_plain(chat_id, text)
    except Exception as e:
        # Surface unexpected failures (import error, bug in our code, etc.)
        # so we see them in Telegram instead of having the webhook return 200
        # with the error buried in Vercel stderr.
        log_event("explain.crash", src=source_key, uid=uid,
                  exc_type=type(e).__name__, exc=str(e)[:200])
        try:
            from api.llm import _mask_secrets as _m
            safe = _m(f"{type(e).__name__}: {e}")
        except Exception:
            safe = f"{type(e).__name__}: ***"
        _send_plain(chat_id, f"Внутренняя ошибка в handle_explain: {safe}")


def _send_plain(chat_id: int, text: str) -> dict:
    """Send a Telegram message with parse_mode disabled — used for
    diagnostic / LLM-output paths where Markdown escaping would be brittle.
    """
    return _tg(
        "sendMessage",
        chat_id=chat_id,
        text=text,
        disable_web_page_preview=True,
    )


# === Webhook dispatcher ===
def _from_user_id(update: dict) -> int | None:
    """Extract the Telegram user id from any update shape we handle."""
    for key in ("callback_query", "message", "edited_message"):
        section = update.get(key)
        if isinstance(section, dict):
            user = section.get("from") or {}
            uid = user.get("id")
            if isinstance(uid, int):
                return uid
    return None


def _from_chat_id(update: dict) -> int | None:
    """Extract a chat_id we can reply to, from any update shape."""
    cb = update.get("callback_query")
    if isinstance(cb, dict):
        msg = cb.get("message") or {}
        chat = msg.get("chat") or {}
        if isinstance(chat.get("id"), int):
            return chat["id"]
    for key in ("message", "edited_message"):
        msg = update.get(key)
        if isinstance(msg, dict):
            chat = msg.get("chat") or {}
            if isinstance(chat.get("id"), int):
                return chat["id"]
    return None


def is_admin(user_id: int | None) -> bool:
    return user_id is not None and user_id in ADMIN_IDS


PRIVATE_BOT_MESSAGE = (
    "🔒 Это приватный бот.\n\n"
    "Доступ только у владельцев. Если ты считаешь, что должен иметь доступ — "
    "напиши тому, кто дал тебе ссылку."
)


def dispatch(update: dict) -> None:
    # Access gate: only admins may interact with anything. Non-admins get a
    # single polite reply (callback taps get the answerCallbackQuery toast)
    # and no further processing. Deep-link shares (/start item_<uid>) also
    # dead-end here — Share buttons are usable but recipients can't read.
    user_id = _from_user_id(update)
    if not is_admin(user_id):
        log_event("access.denied", user_id=user_id,
                  kind="callback" if "callback_query" in update else "message")
        cb = update.get("callback_query")
        if isinstance(cb, dict):
            _answer_callback(cb.get("id", ""), text="🔒 Приватный бот")
            return
        chat_id = _from_chat_id(update)
        if chat_id is not None:
            _send_plain(chat_id, PRIVATE_BOT_MESSAGE)
        return

    if "callback_query" in update:
        handle_callback(update)
        return
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    if not text:
        return

    # Persistent reply_keyboard taps come in as plain text — match before commands.
    REPLY_BUTTON_TO_SOURCE = {
        "📚 Claude Skills": "skills",
        "⚙️ N8N Workflows": "n8n",
        "🧩 Make Workflows": "make",
    }
    if text in REPLY_BUTTON_TO_SOURCE:
        deliver(chat_id, screen_source_menu(REPLY_BUTTON_TO_SOURCE[text]))
        return
    if text == "📋 Меню":
        _handle_start(chat_id)
        return
    if text == "ℹ️ Помощь":
        deliver(chat_id, (HELP_TEXT, None), reply_keyboard=_reply_keyboard())
        return

    # Strip bot mention suffix (e.g. /start@MyBot)
    parts = text.split(maxsplit=1)
    cmd = parts[0]
    arg = parts[1] if len(parts) > 1 else ""
    if "@" in cmd:
        cmd = cmd.split("@", 1)[0]
    if cmd.startswith("/"):
        # has_arg only (not the arg itself — search queries can leak intent
        # if logged verbatim, and they're not needed for usage analytics)
        log_event("command", cmd=cmd, has_arg=bool(arg))
    if cmd in ("/start", "/menu"):
        # Deep link: t.me/<bot>?start=item_<url_id> → jump straight to detail
        if arg.startswith("item_"):
            uid = arg[len("item_"):]
            found = find_item_anywhere(uid)
            if found is not None:
                source_key, _ = found
                deliver(chat_id, screen_item(source_key, uid),
                        reply_keyboard=_reply_keyboard())
                return
        _handle_start(chat_id)
    elif cmd == "/help":
        deliver(chat_id, (HELP_TEXT, None), reply_keyboard=_reply_keyboard())
    elif cmd == "/list":
        deliver(chat_id, screen_page("skills", ALL_VIEW, 0))  # legacy: defaults to skills
    elif cmd == "/categories":
        deliver(chat_id, screen_categories("skills"))
    elif cmd == "/months":
        deliver(chat_id, screen_months("skills"))
    elif cmd == "/skills":
        deliver(chat_id, screen_source_menu("skills"))
    elif cmd == "/n8n":
        deliver(chat_id, screen_source_menu("n8n"))
    elif cmd == "/make":
        deliver(chat_id, screen_source_menu("make"))
    elif cmd == "/search":
        deliver(chat_id, screen_search(arg))
    elif cmd == "/random":
        picked = pick_random_anywhere()
        if picked is None:
            deliver(chat_id, ("Базы пусты.", None))
        else:
            source_key, item = picked
            deliver(chat_id, screen_item(source_key, _url_id(item.get("url") or "")))
    elif cmd == "/stats":
        deliver(chat_id, screen_stats())
    elif cmd == "/whatsnew":
        deliver(chat_id, screen_whatsnew())
    else:
        deliver(
            chat_id,
            ("Не понял команду. Жми кнопки внизу или /menu.", None),
            reply_keyboard=_reply_keyboard(),
        )


def _handle_start(chat_id: int) -> None:
    """``/start`` and the ``📋 Меню`` reply-button: set persistent keyboard, then show picker.

    Two messages so the reply_keyboard is guaranteed visible (Telegram allows
    only one reply_markup per message; the inline picker needs the second).
    """
    deliver(chat_id, ("Открываю меню…", None), reply_keyboard=_reply_keyboard())
    deliver(chat_id, screen_top_menu())


# === HTTP handler ===
class handler(BaseHTTPRequestHandler):  # noqa: N801 (required name by Vercel)
    def do_POST(self):  # noqa: N802
        try:
            # Verify secret token if configured
            if WEBHOOK_SECRET:
                received = self.headers.get(
                    "X-Telegram-Bot-Api-Secret-Token", ""
                )
                if received != WEBHOOK_SECRET:
                    log_event("webhook.auth_fail")
                    self.send_response(401)
                    self.end_headers()
                    return
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(length) if length > 0 else b""
            update = json.loads(body or b"{}")
            dispatch(update)
        except Exception as e:
            log_event("webhook.crash",
                      exc_type=type(e).__name__, exc=str(e)[:200])
        # Always 200 so Telegram does not retry.
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_GET(self):  # noqa: N802
        # Health check — surfaces config state so missing Vercel env vars
        # (especially ANTHROPIC_API_KEY for the explain button) are visible
        # without digging through function logs.
        body = json.dumps({
            "alive": True,
            "bot_token_set": bool(BOT_TOKEN),
            "webhook_secret_set": bool(WEBHOOK_SECRET),
            "llm_enabled": LLM_ENABLED,
            "llm_model": os.environ.get("BOT_LLM_MODEL", "claude-haiku-4-5-20251001") if LLM_ENABLED else None,
            "admin_count": len(ADMIN_IDS),
            "admins_from_env": bool(_admin_env),
            "repo": REPO,
            "branch": BRANCH,
        }).encode()
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(body)
