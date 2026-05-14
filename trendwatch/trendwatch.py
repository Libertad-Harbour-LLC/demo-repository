#!/usr/bin/env python3
"""Trendwatch orchestrator: fetch from sources and post a Telegram digest."""
import argparse
import os
import sys

import config
from sources.github import fetch_github
from sources.reddit import fetch_reddit
from sources.twitter import fetch_twitter
from sources.threads import fetch_threads
import telegram_client


def _safe(name: str, fn, *args, **kwargs) -> list[dict]:
    try:
        return fn(*args, **kwargs) or []
    except Exception as exc:
        print(f"[trendwatch:{name}] unexpected: {exc}", file=sys.stderr)
        return []


def run(dry_run: bool = False) -> int:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not dry_run:
        if not bot_token or not chat_id:
            print("[trendwatch] TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required (or use --dry-run)", file=sys.stderr)
            return 1

    sources_enabled = getattr(config, "SOURCES", {})
    max_items = getattr(config, "MAX_ITEMS_PER_SOURCE", 10)

    items_by_source: dict[str, list[dict]] = {}

    if sources_enabled.get("github"):
        items_by_source["github"] = _safe(
            "github", fetch_github, config.GITHUB_TOPICS, 24, max_items
        )
    if sources_enabled.get("reddit"):
        items_by_source["reddit"] = _safe(
            "reddit",
            fetch_reddit,
            config.REDDIT_SUBREDDITS,
            config.REDDIT_MIN_SCORE,
            24,
            max_items,
        )
    if sources_enabled.get("twitter"):
        items_by_source["twitter"] = _safe(
            "twitter", fetch_twitter, config.KEYWORDS, max_items, 24
        )
    if sources_enabled.get("threads"):
        items_by_source["threads"] = _safe(
            "threads", fetch_threads, config.KEYWORDS, max_items
        )

    counts = " ".join(f"{k}={len(v)}" for k, v in items_by_source.items())
    summary = f"[trendwatch] {counts}"

    if dry_run:
        messages = telegram_client._build_messages(items_by_source)
        for i, m in enumerate(messages, 1):
            print(f"--- message {i} ---")
            print(m)
        print(summary)
        return 0

    try:
        telegram_client.send_digest(items_by_source, bot_token, chat_id)
    except Exception as exc:
        print(f"[trendwatch] telegram send failed: {exc}", file=sys.stderr)
        print(summary)
        return 1

    print(summary)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Trendwatch daily digest")
    parser.add_argument("--dry-run", action="store_true", help="Print composed message instead of sending to Telegram")
    args = parser.parse_args()
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
