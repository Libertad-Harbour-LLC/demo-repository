"""Telegram bot webhook handler (Vercel Python serverless function).

Single-file interactive bot that reads recommendation JSON files from
raw.githubusercontent.com and serves them via Telegram commands and inline
keyboards. Stateless — no DB inside the function, 60s in-process cache.

Supports three data sources: Claude Skills, n8n Workflows, Make Workflows.
"""
from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler
from typing import Any

import requests

# === Constants ===
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
REPO = os.environ.get("BOT_REPO", "Libertad-Harbour-LLC/demo-repository")
BRANCH = os.environ.get("BOT_BRANCH", "main")
CACHE_TTL_SECONDS = 60
PAGE_SIZE = 5  # items per page

# Source registry: each source has a URL, category labels, optional tool filter,
# and a display header.
SOURCES: dict[str, dict[str, Any]] = {
    "skills": {
        "label": "📚 Claude Skills",
        "url": f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/digests/recommended.json",
        "watchlist_url": f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/digests/watchlist.json",
        "categories": {
            "marketing_skill": "📈 Marketing",
            "vibe_coding_skill": "💻 Vibe coding",
            "ai_content_skill": "🎨 AI content",
            "general_skill": "🔧 General",
        },
        "tool_filter": None,
        "header": "Claude Skills",
        "default_category": "general_skill",
    },
    "n8n": {
        "label": "⚙️ N8N Workflows",
        "url": f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/digests/workflows/recommended.json",
        "watchlist_url": f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/digests/workflows/watchlist.json",
        "categories": {
            "marketing_workflow": "📈 Marketing",
            "sales_workflow": "💰 Sales",
            "data_workflow": "📊 Data",
            "devops_workflow": "🛠 DevOps",
            "content_workflow": "🎨 Content",
            "general_workflow": "🔧 General",
        },
        "tool_filter": "n8n",
        "header": "N8N Workflows",
        "default_category": "general_workflow",
    },
    "make": {
        "label": "🧩 Make Workflows",
        "url": f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/digests/workflows/recommended.json",
        "watchlist_url": f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/digests/workflows/watchlist.json",
        "categories": {
            "marketing_workflow": "📈 Marketing",
            "sales_workflow": "💰 Sales",
            "data_workflow": "📊 Data",
            "devops_workflow": "🛠 DevOps",
            "content_workflow": "🎨 Content",
            "general_workflow": "🔧 General",
        },
        "tool_filter": "make",
        "header": "Make Workflows",
        "default_category": "general_workflow",
    },
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
    return _fetch_url(SOURCES[source_key]["url"], {"skills": {}})


def _fetch_watchlist(source_key: str) -> dict:
    """Fetch the watchlist DB for a source (separate file, separate schema)."""
    if source_key not in SOURCES:
        return {"items": {}}
    url = SOURCES[source_key].get("watchlist_url")
    if not url:
        return {"items": {}}
    return _fetch_url(url, {"items": {}})


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
    cat_labels = SOURCES[source_key]["categories"]
    cat_str = f" • {cat_labels.get(cat, cat)}" if cat else ""
    return f"• {status_prefix}{tool_prefix}[{name}]({url}){sub_str}{stars_str}{score_str}{cat_str}"


# === Item selection ===
def _normalize_watch_item(entry: dict) -> dict:
    """Map a watchlist.json entry to the shape ``_format_item_line`` expects.

    Watchlist entries use ``added_date`` instead of ``first_recommended`` and
    lack scoring fields — we just copy what's there and tag with ``_status``.
    """
    out = dict(entry)
    out["_status"] = "watch"
    if "first_recommended" not in out and "added_date" in out:
        out["first_recommended"] = out["added_date"]
    return out


def _all_items_sorted(db: dict, source_key: str) -> list[dict]:
    """Merge recommended + watchlist items for a source.

    Recommended items take precedence: if a URL appears in both files (e.g.
    a watch item that just graduated), only the recommended version is shown.
    Watch items render with a 👀 prefix.
    """
    rec_items = list((db.get("skills") or {}).values())
    rec_urls = {i.get("url") for i in rec_items if i.get("url")}

    watch_db = _fetch_watchlist(source_key)
    watch_items = [
        _normalize_watch_item(e)
        for e in (watch_db.get("items") or {}).values()
        if isinstance(e, dict) and e.get("url") not in rec_urls
    ]

    items = rec_items + watch_items
    tool_filter = SOURCES[source_key]["tool_filter"]
    if tool_filter is not None:
        # Watchlist entries written by older pipeline runs lack a `tool`
        # field. Surface those only under the "n8n" bucket (workflows
        # pipeline defaults to n8n; Make watchlist is empty in practice).
        def _matches(i: dict) -> bool:
            t = i.get("tool")
            if t == tool_filter:
                return True
            if i.get("_status") == "watch" and not t and tool_filter == "n8n":
                return True
            return False
        items = [i for i in items if _matches(i)]
    items.sort(
        key=lambda s: (s.get("first_recommended", ""), s.get("title", "")),
        reverse=True,
    )
    return items


def _filter_by_category(items: list[dict], cat: str, source_key: str) -> list[dict]:
    default_cat = SOURCES[source_key]["default_category"]
    return [s for s in items if s.get("category", default_cat) == cat]


def _filter_by_month(items: list[dict], ym: str) -> list[dict]:
    return [s for s in items if (s.get("first_recommended") or "")[:7] == ym]


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
    for s in chunk:
        lines.append(_format_item_line(s, source_key))

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
    kb_rows: list[list[dict]] = []
    if nav:
        kb_rows.append(nav)
    kb_rows.append([{"text": "« Меню", "callback_data": f"src:{source_key}:menu"}])
    kb_rows.append([{"text": "« Источник", "callback_data": "menu"}])
    return ("\n".join(lines), {"inline_keyboard": kb_rows})


# === Top-level source picker ===
def _top_menu_text() -> str:
    return "*Trendwatch — базы рекомендаций*\n\nВыбери источник:"


def _top_menu_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": SOURCES["skills"]["label"], "callback_data": "src:skills:menu"}],
            [{"text": SOURCES["n8n"]["label"], "callback_data": "src:n8n:menu"}],
            [{"text": SOURCES["make"]["label"], "callback_data": "src:make:menu"}],
        ]
    }


# === Per-source sub-menu ===
def _source_menu_text(source_key: str) -> str:
    return f"*{SOURCES[source_key]['header']}*\n\nВыбери что показать:"


def _source_menu_keyboard(source_key: str) -> dict:
    return {
        "inline_keyboard": [
            [{"text": "📚 Весь список", "callback_data": f"src:{source_key}:list:0"}],
            [{"text": "🏷 По категории", "callback_data": f"src:{source_key}:categories"}],
            [{"text": "📅 По месяцу", "callback_data": f"src:{source_key}:months"}],
            [{"text": "« Источник", "callback_data": "menu"}],
        ]
    }


# === Index views (categories / months) ===
def _build_categories_view(db: dict, source_key: str) -> tuple[str, dict]:
    items = _all_items_sorted(db, source_key)
    default_cat = SOURCES[source_key]["default_category"]
    cat_labels: dict[str, str] = SOURCES[source_key]["categories"]
    cat_counts: dict[str, int] = {}
    for s in items:
        c = s.get("category", default_cat)
        cat_counts[c] = cat_counts.get(c, 0) + 1
    text = f"*Категории {SOURCES[source_key]['header']}:*\n\n"
    rows: list[list[dict]] = []
    for cat, label in cat_labels.items():
        n = cat_counts.get(cat, 0)
        text += f"{label} — {n}\n"
        if n > 0:
            rows.append(
                [
                    {
                        "text": f"{label} ({n})",
                        "callback_data": f"src:{source_key}:cat:{cat}:0",
                    }
                ]
            )
    # Include any unknown categories that exist in data but not in labels
    for cat, n in cat_counts.items():
        if cat not in cat_labels and n > 0:
            label = cat or default_cat
            text += f"{label} — {n}\n"
            rows.append(
                [
                    {
                        "text": f"{label} ({n})",
                        "callback_data": f"src:{source_key}:cat:{cat}:0",
                    }
                ]
            )
    rows.append([{"text": "« Меню", "callback_data": f"src:{source_key}:menu"}])
    rows.append([{"text": "« Источник", "callback_data": "menu"}])
    return text, {"inline_keyboard": rows}


def _build_months_view(db: dict, source_key: str) -> tuple[str, dict]:
    items = _all_items_sorted(db, source_key)
    month_counts: dict[str, int] = {}
    for s in items:
        date = s.get("first_recommended", "") or ""
        if len(date) >= 7:
            ym = date[:7]
            month_counts[ym] = month_counts.get(ym, 0) + 1
    if not month_counts:
        return (
            f"*{SOURCES[source_key]['header']}*\n\nПусто.",
            {
                "inline_keyboard": [
                    [{"text": "« Меню", "callback_data": f"src:{source_key}:menu"}],
                    [{"text": "« Источник", "callback_data": "menu"}],
                ]
            },
        )
    months_sorted = sorted(month_counts.keys(), reverse=True)
    rows: list[list[dict]] = []
    text = f"*{SOURCES[source_key]['header']} — по месяцам:*\n\n"
    for ym in months_sorted:
        n = month_counts[ym]
        text += f"📅 {ym} — {n}\n"
        rows.append(
            [
                {
                    "text": f"{ym} ({n})",
                    "callback_data": f"src:{source_key}:month:{ym}:0",
                }
            ]
        )
    rows.append([{"text": "« Меню", "callback_data": f"src:{source_key}:menu"}])
    rows.append([{"text": "« Источник", "callback_data": "menu"}])
    return text, {"inline_keyboard": rows}


# === Render dispatchers (shared by send + edit paths) ===
def _render_list_page(source_key: str, page: int) -> tuple[str, dict]:
    db = _fetch(source_key)
    items = _all_items_sorted(db, source_key)
    title = f"Все — {SOURCES[source_key]['header']}"
    return _render_page(items, page, title, source_key, "list")


def _render_category_page(source_key: str, cat: str, page: int) -> tuple[str, dict]:
    db = _fetch(source_key)
    items = _filter_by_category(_all_items_sorted(db, source_key), cat, source_key)
    cat_labels = SOURCES[source_key]["categories"]
    label = cat_labels.get(cat, cat or SOURCES[source_key]["default_category"])
    title = f"{SOURCES[source_key]['header']} — {label}"
    return _render_page(items, page, title, source_key, f"cat:{cat}")


def _render_month_page(source_key: str, ym: str, page: int) -> tuple[str, dict]:
    db = _fetch(source_key)
    items = _filter_by_month(_all_items_sorted(db, source_key), ym)
    title = f"{SOURCES[source_key]['header']} — 📅 {ym}"
    return _render_page(items, page, title, source_key, f"month:{ym}")


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
    "/list, /categories, /months — устаревший доступ к skills\n"
    "/help — это сообщение\n"
    "\n"
    "База обновляется через GitHub-репозиторий; в каждом дайджесте под пунктами есть прямые ссылки на источники."
)


# === Command handlers (send new message) ===
# Every fresh send_message from a command attaches the persistent reply_keyboard
# (alongside inline_keyboard when present, Telegram picks one — but the most
# recent reply_keyboard stays visible client-side regardless).
def handle_start(chat_id: int) -> None:
    # Top-level picker uses inline_keyboard; we send a tiny preamble first
    # with the reply_keyboard so the persistent bar is guaranteed visible,
    # then the picker itself. To keep chat clean: send single message with
    # inline_keyboard AND set reply_keyboard separately on a follow-up only
    # if needed. Simpler: send picker with inline_keyboard; rely on a recent
    # reply_keyboard message. Here we send the picker, then a no-op message
    # would be noisy — instead attach reply_keyboard to the picker itself by
    # sending the reply_keyboard first as a quick "menu set" message.
    # Cleanest implementation: send picker with inline_keyboard; the
    # reply_keyboard is delivered via a separate one-time setter message on
    # /start so the bar is set once per session.
    _send_message(chat_id, "Открываю меню…", reply_keyboard=_reply_keyboard())
    _send_message(chat_id, _top_menu_text(), _top_menu_keyboard())


def handle_help(chat_id: int) -> None:
    _send_message(chat_id, HELP_TEXT, reply_keyboard=_reply_keyboard())


def handle_source_menu(chat_id: int, source_key: str) -> None:
    _send_message(
        chat_id,
        _source_menu_text(source_key),
        _source_menu_keyboard(source_key),
    )


def handle_list(chat_id: int, source_key: str, page: int = 0) -> None:
    text, kb = _render_list_page(source_key, page)
    _send_message(chat_id, text, kb)


def handle_categories(chat_id: int, source_key: str) -> None:
    db = _fetch(source_key)
    text, kb = _build_categories_view(db, source_key)
    _send_message(chat_id, text, kb)


def handle_months(chat_id: int, source_key: str) -> None:
    db = _fetch(source_key)
    text, kb = _build_months_view(db, source_key)
    _send_message(chat_id, text, kb)


# === Edit-in-place helpers (used by callback queries) ===
def _edit_top_menu(chat_id: int, message_id: int) -> None:
    _edit_message(chat_id, message_id, _top_menu_text(), _top_menu_keyboard())


def _edit_source_menu(chat_id: int, message_id: int, source_key: str) -> None:
    _edit_message(
        chat_id, message_id, _source_menu_text(source_key), _source_menu_keyboard(source_key)
    )


def _edit_categories(chat_id: int, message_id: int, source_key: str) -> None:
    db = _fetch(source_key)
    text, kb = _build_categories_view(db, source_key)
    _edit_message(chat_id, message_id, text, kb)


def _edit_months(chat_id: int, message_id: int, source_key: str) -> None:
    db = _fetch(source_key)
    text, kb = _build_months_view(db, source_key)
    _edit_message(chat_id, message_id, text, kb)


def _edit_list(chat_id: int, message_id: int, source_key: str, page: int) -> None:
    text, kb = _render_list_page(source_key, page)
    _edit_message(chat_id, message_id, text, kb)


def _edit_category(
    chat_id: int, message_id: int, source_key: str, cat: str, page: int
) -> None:
    text, kb = _render_category_page(source_key, cat, page)
    _edit_message(chat_id, message_id, text, kb)


def _edit_month(
    chat_id: int, message_id: int, source_key: str, ym: str, page: int
) -> None:
    text, kb = _render_month_page(source_key, ym, page)
    _edit_message(chat_id, message_id, text, kb)


# === Callback handlers ===
def handle_callback(update: dict) -> None:
    cb = update["callback_query"]
    chat_id = cb["message"]["chat"]["id"]
    message_id = cb["message"]["message_id"]
    cb_id = cb["id"]
    data = cb.get("data", "") or ""

    # Acknowledge fast (Telegram shows spinner otherwise).
    _answer_callback(cb_id)

    # Top-level picker
    if data == "menu":
        _edit_top_menu(chat_id, message_id)
        return

    # Source-scoped routes: src:<source_key>:<action>[:<args>]
    if data.startswith("src:"):
        parts = data.split(":")
        if len(parts) < 3:
            return
        source_key = parts[1]
        if source_key not in VALID_SOURCES:
            return
        action = parts[2]

        if action == "menu":
            _edit_source_menu(chat_id, message_id, source_key)
            return
        if action == "categories":
            _edit_categories(chat_id, message_id, source_key)
            return
        if action == "months":
            _edit_months(chat_id, message_id, source_key)
            return
        if action == "list":
            # src:<source>:list:<page>
            try:
                page = int(parts[3]) if len(parts) >= 4 else 0
            except ValueError:
                page = 0
            _edit_list(chat_id, message_id, source_key, page)
            return
        if action == "cat":
            # src:<source>:cat:<cat>:<page>
            if len(parts) >= 5:
                cat = parts[3]
                try:
                    page = int(parts[4])
                except ValueError:
                    page = 0
                _edit_category(chat_id, message_id, source_key, cat, page)
            return
        if action == "month":
            # src:<source>:month:<YYYY-MM>:<page>
            if len(parts) >= 5:
                ym = parts[3]
                try:
                    page = int(parts[4])
                except ValueError:
                    page = 0
                _edit_month(chat_id, message_id, source_key, ym, page)
            return


# === Webhook dispatcher ===
def dispatch(update: dict) -> None:
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

    # === Persistent reply_keyboard button labels (sent as plain text) ===
    # Match BEFORE slash-command handling so taps route correctly.
    if text == "📚 Claude Skills":
        handle_source_menu(chat_id, "skills")
        return
    if text == "⚙️ N8N Workflows":
        handle_source_menu(chat_id, "n8n")
        return
    if text == "🧩 Make Workflows":
        handle_source_menu(chat_id, "make")
        return
    if text == "📋 Меню":
        handle_start(chat_id)
        return
    if text == "ℹ️ Помощь":
        handle_help(chat_id)
        return

    # Strip bot mention suffix (e.g. /start@MyBot)
    cmd = text.split()[0] if text else ""
    if "@" in cmd:
        cmd = cmd.split("@", 1)[0]
    if cmd == "/start" or cmd == "/menu":
        handle_start(chat_id)
    elif cmd == "/help":
        handle_help(chat_id)
    elif cmd == "/list":
        # Backwards-compat: default to skills.
        handle_list(chat_id, "skills", 0)
    elif cmd == "/categories":
        handle_categories(chat_id, "skills")
    elif cmd == "/months":
        handle_months(chat_id, "skills")
    elif cmd == "/skills":
        handle_source_menu(chat_id, "skills")
    elif cmd == "/n8n":
        handle_source_menu(chat_id, "n8n")
    elif cmd == "/make":
        handle_source_menu(chat_id, "make")
    else:
        _send_message(
            chat_id,
            "Не понял команду. Жми кнопки внизу или /menu.",
            reply_keyboard=_reply_keyboard(),
        )


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
                    self.send_response(401)
                    self.end_headers()
                    return
            length = int(self.headers.get("Content-Length", 0) or 0)
            body = self.rfile.read(length) if length > 0 else b""
            update = json.loads(body or b"{}")
            dispatch(update)
        except Exception as e:
            print(f"[bot] error: {e}", file=sys.stderr)
        # Always 200 so Telegram does not retry.
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def do_GET(self):  # noqa: N802
        # Health check
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"trendwatch bot is alive")
