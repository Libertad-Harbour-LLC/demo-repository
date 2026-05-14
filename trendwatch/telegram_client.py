"""Telegram digest sender."""
from datetime import datetime, timezone

import requests

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
MAX_LEN = 3800

SOURCE_META = {
    "github": ("\U0001f4e6", "GitHub"),
    "reddit": ("\U0001f916", "Reddit"),
    "twitter": ("\U0001f426", "X"),
    "threads": ("\U0001f9f5", "Threads"),
}

_MD_ESCAPE = set("_*[]()~`>#+-=|{}.!")
_URL_ESCAPE = set(")\\")


def _escape(text: str) -> str:
    out = []
    for ch in text:
        if ch in _MD_ESCAPE:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def _escape_url(url: str) -> str:
    out = []
    for ch in url:
        if ch in _URL_ESCAPE:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def _format_group(source: str, items: list[dict]) -> str:
    emoji, label = SOURCE_META.get(source, ("\U0001f517", source.title()))
    lines = [f"\n{emoji} *{_escape(label)}*"]
    for it in items:
        title = _escape(it.get("title", ""))
        url = _escape_url(it.get("url", ""))
        meta = it.get("meta", "")
        line = f"• [{title}]({url})"
        if meta:
            line += f" {_escape('—')} {_escape(meta)}"
        lines.append(line)
    return "\n".join(lines)


def _header() -> str:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"\U0001f525 *Trendwatch {_escape(today)}*"


def _split_group(group: str) -> list[str]:
    """Split a single group's text into chunks <= MAX_LEN, line-by-line.

    Keeps the source header line only on the first chunk.
    """
    if len(group) <= MAX_LEN:
        return [group]
    lines = group.split("\n")
    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = current + "\n" + line if current else line
        if len(candidate) > MAX_LEN and current:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _build_messages(items_by_source: dict[str, list[dict]]) -> list[str]:
    header = _header()
    groups: list[str] = []
    for source in ("github", "reddit", "twitter", "threads"):
        items = items_by_source.get(source) or []
        if not items:
            continue
        groups.append(_format_group(source, items))

    if not groups:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return [f"\U0001f525 Trendwatch {_escape(today)}\nNo new items today\\."]

    # Expand any oversized group into multiple sub-chunks first.
    expanded: list[str] = []
    for group in groups:
        expanded.extend(_split_group(group))

    messages: list[str] = []
    current = header
    for chunk in expanded:
        candidate = current + "\n" + chunk if current else chunk
        if len(candidate) > MAX_LEN and current:
            messages.append(current)
            current = chunk
        else:
            current = candidate
    if current:
        messages.append(current)
    return messages


def send_digest(items_by_source: dict[str, list[dict]], bot_token: str, chat_id: str) -> None:
    messages = _build_messages(items_by_source)
    url = API_URL.format(token=bot_token)
    for msg in messages:
        payload = {
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "MarkdownV2",
            "disable_web_page_preview": True,
        }
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
