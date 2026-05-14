"""Telegram bot webhook handler (Vercel Python serverless function).

Single-file interactive bot that reads digests/recommended.json from
raw.githubusercontent.com and serves it via Telegram commands and inline
keyboards. Stateless — no DB inside the function, 60s in-process cache.
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
RECOMMENDED_URL = (
    f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/digests/recommended.json"
)
CACHE_TTL_SECONDS = 60
PAGE_SIZE = 5  # skills per page

CATEGORY_LABELS = {
    "marketing_skill": "📈 Marketing",
    "vibe_coding_skill": "💻 Vibe coding",
    "ai_content_skill": "🎨 AI content",
    "general_skill": "🔧 General",
}

# === In-process cache ===
_cache: dict[str, Any] = {"data": None, "fetched_at": 0.0}


def _fetch_recommended() -> dict:
    now = time.time()
    if _cache["data"] is not None and now - _cache["fetched_at"] < CACHE_TTL_SECONDS:
        return _cache["data"]
    try:
        resp = requests.get(RECOMMENDED_URL, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
        else:
            data = {"skills": {}}
    except Exception:
        data = _cache["data"] or {"skills": {}}
    _cache["data"] = data
    _cache["fetched_at"] = now
    return data


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


def _send_message(chat_id: int, text: str, reply_markup: dict | None = None) -> dict:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
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


def _format_skill_line(skill: dict) -> str:
    name = _md_escape(skill.get("title") or skill.get("repo_full_name", "?"))
    url = skill.get("url", "")
    skills_in_repo = skill.get("skills_in_repo") or skill.get("skills") or []
    if isinstance(skills_in_repo, list) and skills_in_repo:
        names: list[str] = []
        for s in skills_in_repo[:5]:
            if isinstance(s, str):
                names.append(s)
            elif isinstance(s, dict):
                names.append(s.get("name", ""))
        names = [n for n in names if n]
        more = "…" if len(skills_in_repo) > 5 else ""
        if names:
            skill_str = (
                f" ({len(skills_in_repo)} skills: {', '.join(names)}{more})"
            )
        else:
            skill_str = f" ({len(skills_in_repo)} skills)"
    else:
        skill_str = ""
    stars = skill.get("stars")
    stars_str = f" ⭐ {stars}" if isinstance(stars, int) else ""
    score = skill.get("final_score")
    score_str = (
        f" • score {score}"
        if isinstance(score, (int, float)) and not isinstance(score, bool)
        else ""
    )
    cat = skill.get("category", "")
    cat_str = f" • {CATEGORY_LABELS.get(cat, cat)}" if cat else ""
    return f"• [{name}]({url}){skill_str}{stars_str}{score_str}{cat_str}"


# === Skill selection ===
def _all_skills_sorted(db: dict) -> list[dict]:
    skills = list((db.get("skills") or {}).values())
    skills.sort(
        key=lambda s: (s.get("first_recommended", ""), s.get("title", "")),
        reverse=True,
    )
    return skills


def _filter_by_category(skills: list[dict], cat: str) -> list[dict]:
    return [s for s in skills if s.get("category", "general_skill") == cat]


def _filter_by_month(skills: list[dict], ym: str) -> list[dict]:
    return [s for s in skills if (s.get("first_recommended") or "")[:7] == ym]


# === Page rendering ===
def _render_page(
    skills: list[dict],
    page: int,
    title: str,
    source_token: str,
) -> tuple[str, dict]:
    """Render a single page of skills.

    `source_token` is the callback prefix for navigation, e.g.
    "list", "cat:marketing_skill", "month:2026-05".
    """
    total = len(skills)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    chunk = skills[start:end]

    if not chunk:
        kb = {"inline_keyboard": [[{"text": "« Меню", "callback_data": "menu"}]]}
        return (f"*{title}*\n\nПусто.", kb)

    lines = [f"*{title}* — стр. {page+1}/{total_pages} ({total} всего)\n"]
    for s in chunk:
        lines.append(_format_skill_line(s))

    nav: list[dict] = []
    if page > 0:
        nav.append(
            {"text": "← Назад", "callback_data": f"{source_token}:{page-1}"}
        )
    if end < total:
        nav.append(
            {"text": "Дальше →", "callback_data": f"{source_token}:{page+1}"}
        )
    kb_rows: list[list[dict]] = []
    if nav:
        kb_rows.append(nav)
    kb_rows.append([{"text": "« Меню", "callback_data": "menu"}])
    return ("\n".join(lines), {"inline_keyboard": kb_rows})


# === Menu rendering ===
def _menu_text() -> str:
    return (
        "*Trendwatch — Claude Skills DB*\n\n"
        "Привет! Я храню все рекомендованные Claude Skills.\n\n"
        "Выбери что показать:"
    )


def _menu_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "📚 Весь список", "callback_data": "list:0"}],
            [{"text": "🏷 По категории", "callback_data": "categories"}],
            [{"text": "📅 По месяцу", "callback_data": "months"}],
        ]
    }


# === Index views (categories / months) ===
def _build_categories_view(db: dict) -> tuple[str, dict]:
    skills = _all_skills_sorted(db)
    cat_counts: dict[str, int] = {}
    for s in skills:
        c = s.get("category", "general_skill")
        cat_counts[c] = cat_counts.get(c, 0) + 1
    text = "*Категории Claude Skills:*\n\n"
    rows: list[list[dict]] = []
    for cat, label in CATEGORY_LABELS.items():
        n = cat_counts.get(cat, 0)
        text += f"{label} — {n}\n"
        if n > 0:
            rows.append(
                [{"text": f"{label} ({n})", "callback_data": f"cat:{cat}:0"}]
            )
    # Include any unknown categories that exist in data but not in labels
    for cat, n in cat_counts.items():
        if cat not in CATEGORY_LABELS and n > 0:
            label = cat or "general_skill"
            text += f"{label} — {n}\n"
            rows.append(
                [{"text": f"{label} ({n})", "callback_data": f"cat:{cat}:0"}]
            )
    rows.append([{"text": "« Меню", "callback_data": "menu"}])
    return text, {"inline_keyboard": rows}


def _build_months_view(db: dict) -> tuple[str, dict]:
    skills = _all_skills_sorted(db)
    month_counts: dict[str, int] = {}
    for s in skills:
        date = s.get("first_recommended", "") or ""
        if len(date) >= 7:
            ym = date[:7]
            month_counts[ym] = month_counts.get(ym, 0) + 1
    if not month_counts:
        return (
            "Пусто.",
            {"inline_keyboard": [[{"text": "« Меню", "callback_data": "menu"}]]},
        )
    months_sorted = sorted(month_counts.keys(), reverse=True)
    rows: list[list[dict]] = []
    text = "*По месяцам:*\n\n"
    for ym in months_sorted:
        n = month_counts[ym]
        text += f"📅 {ym} — {n}\n"
        rows.append([{"text": f"{ym} ({n})", "callback_data": f"month:{ym}:0"}])
    rows.append([{"text": "« Меню", "callback_data": "menu"}])
    return text, {"inline_keyboard": rows}


# === Render dispatchers (shared by send + edit paths) ===
def _render_list_page(page: int) -> tuple[str, dict]:
    db = _fetch_recommended()
    skills = _all_skills_sorted(db)
    return _render_page(skills, page, "Все skills", "list")


def _render_category_page(cat: str, page: int) -> tuple[str, dict]:
    db = _fetch_recommended()
    skills = _filter_by_category(_all_skills_sorted(db), cat)
    label = CATEGORY_LABELS.get(cat, cat or "general_skill")
    return _render_page(skills, page, label, f"cat:{cat}")


def _render_month_page(ym: str, page: int) -> tuple[str, dict]:
    db = _fetch_recommended()
    skills = _filter_by_month(_all_skills_sorted(db), ym)
    return _render_page(skills, page, f"📅 {ym}", f"month:{ym}")


# === Command handlers (send new message) ===
def handle_start(chat_id: int) -> None:
    _send_message(chat_id, _menu_text(), _menu_keyboard())


def handle_list(chat_id: int, page: int = 0) -> None:
    text, kb = _render_list_page(page)
    _send_message(chat_id, text, kb)


def handle_categories(chat_id: int) -> None:
    db = _fetch_recommended()
    text, kb = _build_categories_view(db)
    _send_message(chat_id, text, kb)


def handle_months(chat_id: int) -> None:
    db = _fetch_recommended()
    text, kb = _build_months_view(db)
    _send_message(chat_id, text, kb)


# === Edit-in-place helpers (used by callback queries) ===
def _edit_menu(chat_id: int, message_id: int) -> None:
    _edit_message(chat_id, message_id, _menu_text(), _menu_keyboard())


def _edit_categories(chat_id: int, message_id: int) -> None:
    db = _fetch_recommended()
    text, kb = _build_categories_view(db)
    _edit_message(chat_id, message_id, text, kb)


def _edit_months(chat_id: int, message_id: int) -> None:
    db = _fetch_recommended()
    text, kb = _build_months_view(db)
    _edit_message(chat_id, message_id, text, kb)


def _edit_list(chat_id: int, message_id: int, page: int) -> None:
    text, kb = _render_list_page(page)
    _edit_message(chat_id, message_id, text, kb)


def _edit_category(chat_id: int, message_id: int, cat: str, page: int) -> None:
    text, kb = _render_category_page(cat, page)
    _edit_message(chat_id, message_id, text, kb)


def _edit_month(chat_id: int, message_id: int, ym: str, page: int) -> None:
    text, kb = _render_month_page(ym, page)
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

    if data == "menu":
        _edit_menu(chat_id, message_id)
        return
    if data == "categories":
        _edit_categories(chat_id, message_id)
        return
    if data == "months":
        _edit_months(chat_id, message_id)
        return
    if data.startswith("list:"):
        try:
            page = int(data.split(":", 1)[1])
        except (ValueError, IndexError):
            page = 0
        _edit_list(chat_id, message_id, page)
        return
    if data.startswith("cat:"):
        parts = data.split(":")
        # "cat:<cat>:<page>"
        if len(parts) >= 3:
            cat = parts[1]
            try:
                page = int(parts[2])
            except ValueError:
                page = 0
            _edit_category(chat_id, message_id, cat, page)
        return
    if data.startswith("month:"):
        parts = data.split(":")
        # "month:<YYYY-MM>:<page>"
        if len(parts) >= 3:
            ym = parts[1]
            try:
                page = int(parts[2])
            except ValueError:
                page = 0
            _edit_month(chat_id, message_id, ym, page)
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
    # Strip bot mention suffix (e.g. /start@MyBot)
    cmd = text.split()[0] if text else ""
    if "@" in cmd:
        cmd = cmd.split("@", 1)[0]
    if cmd == "/start":
        handle_start(chat_id)
    elif cmd == "/list":
        handle_list(chat_id, 0)
    elif cmd == "/categories":
        handle_categories(chat_id)
    elif cmd == "/months":
        handle_months(chat_id)
    else:
        _send_message(
            chat_id,
            "Команды: /start /list /categories /months",
            _menu_keyboard(),
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
