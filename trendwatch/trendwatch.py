#!/usr/bin/env python3
"""Trendwatch orchestrator: fetch -> normalize+deltas -> LLM analyze -> Telegram.

The LLM step (analyzer) is the new heart of the pipeline; on failure we fall
back to the original "list of links" digest so the user still gets something
in Telegram.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

import config
from sources.github import fetch_github
from sources.reddit import fetch_reddit
from sources.twitter import fetch_twitter
from sources.threads import fetch_threads
import telegram_client

import analyzer
import normalizer
import report
import state


def _is_worth_showing(item: dict) -> bool:
    """Dedupe filter: include items only if new, gained skills, or grew ≥5 stars."""
    if item.get("is_new", True):
        return True
    if item.get("has_new_skills"):
        return True
    delta = item.get("delta_stars") or 0
    if isinstance(delta, int) and delta >= 5:
        return True
    return False


def _safe(name: str, fn, *args, **kwargs) -> list[dict]:
    try:
        return fn(*args, **kwargs) or []
    except Exception as exc:
        print(f"[trendwatch:{name}] unexpected: {exc}", file=sys.stderr)
        return []


def _fetch_all() -> dict[str, list[dict]]:
    sources_enabled = getattr(config, "SOURCES", {})
    max_items = getattr(config, "MAX_ITEMS_PER_SOURCE", 10)

    items_by_source: dict[str, list[dict]] = {}
    if sources_enabled.get("github"):
        items_by_source["github"] = _safe(
            "github",
            fetch_github,
            config.GITHUB_TOPICS,
            getattr(config, "GITHUB_CODE_QUERIES", []),
            24,
            max_items,
            getattr(config, "VERIFY_GITHUB_SKILLS", True),
        )
    if sources_enabled.get("reddit"):
        items_by_source["reddit"] = _safe(
            "reddit",
            fetch_reddit,
            config.REDDIT_SUBREDDITS,
            config.REDDIT_MIN_SCORE,
            24,
            max_items,
            getattr(config, "REDDIT_KEYWORDS_FILTER", None),
        )
    if sources_enabled.get("twitter"):
        items_by_source["twitter"] = _safe(
            "twitter", fetch_twitter, config.KEYWORDS, max_items, 24
        )
    if sources_enabled.get("threads"):
        items_by_source["threads"] = _safe(
            "threads", fetch_threads, config.KEYWORDS, max_items
        )
    return items_by_source


def _write_report(analysis: dict, date: str) -> str:
    os.makedirs("digests", exist_ok=True)
    path = os.path.join("digests", f"{date}.md")
    md = report.to_markdown(analysis, date)
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    return path


def run(dry_run: bool = False, no_analyzer: bool = False) -> int:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not dry_run:
        if not bot_token or not chat_id:
            print(
                "[trendwatch] TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required "
                "(or use --dry-run)",
                file=sys.stderr,
            )
            return 1

    items_by_source = _fetch_all()
    counts = " ".join(f"{k}={len(v)}" for k, v in items_by_source.items())
    summary = f"[trendwatch] {counts}"

    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    period = "24h"

    if dry_run:
        messages = telegram_client._build_messages(items_by_source)
        for i, m in enumerate(messages, 1):
            print(f"--- message {i} ---")
            print(m)
        print("[DRY_RUN]")
        print(summary)
        return 0

    if no_analyzer:
        try:
            telegram_client.send_digest(items_by_source, bot_token, chat_id)
        except Exception as exc:
            print(f"[trendwatch] telegram send failed: {exc}", file=sys.stderr)
            print(summary)
            return 1
        print("[FALLBACK_LINKS] --no-analyzer requested")
        print(summary)
        return 0

    # --- Analyzer pipeline ---
    prev_state = state.load_state()
    items_with_deltas = state.compute_deltas(items_by_source, prev_state)
    normalized, _annotated = normalizer.normalize(items_by_source)

    # Dedupe filter: drop items that were already shown without material change.
    filtered_items = [it for it in items_with_deltas if _is_worth_showing(it)]

    if not filtered_items:
        msg = (
            f"\U0001f680 Daily Skill Radar — {date}\n\n"
            "Нет новых Claude Skills за период. Все обнаруженные репозитории "
            "уже были в предыдущих дайджестах без значимого роста.\n\n"
            f"\U0001f4ca Источников проверено: {', '.join(items_by_source.keys())}"
        )
        try:
            telegram_client.send_text(msg, bot_token, chat_id)
        except Exception as exc:
            print(f"[trendwatch] telegram send_text failed: {exc}", file=sys.stderr)
            print(summary)
            return 1
        # Still save state so we don't re-find the same items next run.
        try:
            state.save_state(items_by_source)
        except Exception as exc:
            print(f"[trendwatch] state save failed: {exc}", file=sys.stderr)
        print("[NO_NEW_ITEMS]")
        print(summary)
        return 0

    try:
        analysis = analyzer.analyze(
            normalized, filtered_items, period=period, date=date
        )
    except Exception as exc:
        print(
            f"[trendwatch] analyzer failed: {exc}; falling back to link digest",
            file=sys.stderr,
        )
        try:
            telegram_client.send_digest(items_by_source, bot_token, chat_id)
        except Exception as exc2:
            print(f"[trendwatch] telegram fallback failed: {exc2}", file=sys.stderr)
            print(summary)
            return 1
        print("[FALLBACK_LINKS] LLM analysis failed, sent link list.")
        print(summary)
        return 0

    try:
        report_path = _write_report(analysis, date)
        print(f"[trendwatch] wrote {report_path}")
        try:
            state.save_state(items_by_source)
        except Exception as exc:
            print(f"[trendwatch] state save failed: {exc}", file=sys.stderr)
    except Exception as exc:
        print(f"[trendwatch] report write failed: {exc}", file=sys.stderr)

    telegram_text = analysis.get("telegram_summary") or ""
    if not telegram_text:
        print(
            "[trendwatch] analysis had empty telegram_summary; falling back",
            file=sys.stderr,
        )
        try:
            telegram_client.send_digest(items_by_source, bot_token, chat_id)
        except Exception as exc:
            print(f"[trendwatch] telegram fallback failed: {exc}", file=sys.stderr)
            print(summary)
            return 1
        print("[FALLBACK_LINKS] empty summary, sent link list.")
        print(summary)
        return 0

    try:
        telegram_client.send_text(telegram_text, bot_token, chat_id)
    except Exception as exc:
        print(f"[trendwatch] telegram send_text failed: {exc}", file=sys.stderr)
        print(summary)
        return 1

    print("[ANALYSIS_OK]")
    print(summary)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Trendwatch daily digest")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print composed message instead of sending to Telegram (no API calls)",
    )
    parser.add_argument(
        "--no-analyzer",
        action="store_true",
        help="Skip LLM analysis and state I/O; send the legacy link digest",
    )
    args = parser.parse_args()
    return run(dry_run=args.dry_run, no_analyzer=args.no_analyzer)


if __name__ == "__main__":
    sys.exit(main())
