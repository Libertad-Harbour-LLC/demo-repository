#!/usr/bin/env python3
"""Open Source radar orchestrator: fetch -> deltas -> LLM analyze -> Telegram.

Mirrors ``workflows/workflows.py`` but targets ready-to-use / self-hostable
open-source products & platforms. Reuses trendwatch primitives (state,
skill_db, analyzer, telegram_client, index_writer, report). Data lives under
``digests/opensource/``. Runs on a ~3-day cadence (see opensource.yml).
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from trendwatch import analyzer  # noqa: E402
from trendwatch import index_writer  # noqa: E402
from trendwatch import report  # noqa: E402
from trendwatch import skill_db  # noqa: E402
from trendwatch import state  # noqa: E402
from trendwatch import telegram_client  # noqa: E402

from opensource import config  # noqa: E402
from opensource import normalizer  # noqa: E402
from opensource.prompts import SYSTEM_PROMPT as OSS_SYSTEM_PROMPT  # noqa: E402
from opensource.sources.github import fetch_opensource  # noqa: E402


def _is_worth_showing(item: dict) -> bool:
    """New repos, seeds, ≥5 star growth, or absolute stars ≥30 reach the LLM."""
    if item.get("_seed"):
        return True
    if item.get("is_new", True):
        return True
    delta = item.get("delta_stars") or 0
    if isinstance(delta, int) and delta >= 5:
        return True
    stars = item.get("stars") or 0
    if isinstance(stars, int) and stars >= 30:
        return True
    return False


def _safe(name: str, fn, *args, **kwargs) -> list[dict]:
    try:
        return fn(*args, **kwargs) or []
    except Exception as exc:
        print(f"[opensource:{name}] unexpected: {exc}", file=sys.stderr)
        return []


def _fetch_all() -> dict[str, list[dict]]:
    enabled = getattr(config, "SOURCES", {})
    out: dict[str, list[dict]] = {}
    if enabled.get("github_oss"):
        out["github_oss"] = _safe(
            "github",
            fetch_opensource,
            config.GITHUB_TOPICS,
            config.GITHUB_DESC_QUERIES,
            config.SEED_REPOS,
            config.MAX_ITEMS_PER_SOURCE,
        )
    return out


def _build_cross_source_map(annotated_items: list[dict]) -> dict[str, int]:
    name_sources: dict[str, set[str]] = {}
    for it in annotated_items or []:
        src = it.get("source") or ""
        if not src:
            continue
        for name in it.get("matched_names") or []:
            name_sources.setdefault(name, set()).add(src)
    out: dict[str, int] = {}
    for it in annotated_items or []:
        url = it.get("url")
        if not url:
            continue
        best = 1
        for name in it.get("matched_names") or []:
            best = max(best, len(name_sources.get(name, {it.get("source") or ""})))
        out[url] = max(out.get(url, 0), best)
    return out


def _annotate_cross_source(items: list[dict], cross_map: dict[str, int]) -> list[dict]:
    for it in items or []:
        url = it.get("url")
        if url and url in cross_map:
            it["cross_source_count"] = cross_map[url]
    return items


def _baseline_metrics(items: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for it in items or []:
        url = it.get("url") or ""
        if not url:
            continue
        out[url] = {
            "stars": it.get("stars"),
            "skills_count": None,
            "cross_source_count": it.get("cross_source_count"),
        }
    return out


def _force_promote_seeds(analysis: dict, items: list[dict]) -> None:
    """Ensure every owner seed (``_seed: true``) is in ``top_test`` so it gets
    saved to recommended. Code-level safety net behind the prompt's seed rule:
    a seed the model left in top_watch/excluded is moved/synthesised into
    top_test (and removed from top_watch). Mutates ``analysis``.
    """
    seeds = {it.get("url"): it for it in (items or [])
             if it.get("_seed") and it.get("url")}
    if not seeds:
        return
    top_test = analysis.setdefault("top_test", [])
    if not isinstance(top_test, list):
        top_test = analysis["top_test"] = []
    top_watch = analysis.get("top_watch") or []
    test_urls = {t.get("url") for t in top_test if isinstance(t, dict)}
    watch_by_url = {w.get("url"): w for w in top_watch
                    if isinstance(w, dict) and w.get("url")}

    promoted: list[str] = []
    for url, item in seeds.items():
        if url in test_urls:
            continue
        entry = watch_by_url.get(url)
        if isinstance(entry, dict):
            e = dict(entry)
            e["decision"] = "test_now"
            e.setdefault("what", e.get("why_interesting", ""))
        else:
            e = {
                "name": item.get("repo_full_name") or item.get("title") or url,
                "url": url,
                "source": "github",
                "category": "general_oss",
                "decision": "test_now",
                "description": (item.get("description") or "")[:300],
                "what": item.get("description") or "",
            }
        e.setdefault("category", "general_oss")
        if item.get("stars") is not None:
            e["stars"] = item.get("stars")
        top_test.append(e)
        promoted.append(url)

    if promoted:
        analysis["top_watch"] = [
            w for w in top_watch
            if not (isinstance(w, dict) and w.get("url") in promoted)
        ]
        print(f"[opensource] force-promoted {len(promoted)} seed(s) to recommended",
              file=sys.stderr)


def _backfill_promo_meta(analysis: dict, items: list[dict]) -> None:
    """Copy real ``stars``/``forks`` from fetched items onto top_test/top_watch
    entries (the analyzer omits them), so the catalog/bot show true counts."""
    by_url = {it.get("url"): it for it in (items or []) if it.get("url")}
    for bucket in ("top_test", "top_watch"):
        for e in analysis.get(bucket) or []:
            if not isinstance(e, dict):
                continue
            item = by_url.get(e.get("url"))
            if not item:
                continue
            if e.get("stars") is None and item.get("stars") is not None:
                e["stars"] = item.get("stars")
            if e.get("forks") is None and item.get("forks") is not None:
                e["forks"] = item.get("forks")


def _write_report(analysis: dict, date: str) -> str:
    os.makedirs(config.DIGEST_DIR, exist_ok=True)
    path = os.path.join(config.DIGEST_DIR, f"{date}.md")
    md = report.to_markdown(analysis, date)
    md = md.replace(f"# Daily Skill Radar — {date}", f"# Open Source Radar — {date}", 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    return path


def run(dry_run: bool = False, no_analyzer: bool = False, force: bool = False) -> int:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not dry_run and (not bot_token or not chat_id):
        print("[opensource] TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID required "
              "(or use --dry-run)", file=sys.stderr)
        return 1

    if not dry_run and not force and state.was_sent_today(path=config.STATE_PATH):
        print("[ALREADY_SENT_TODAY] opensource digest already sent today, skipping")
        return 0

    items_by_source = _fetch_all()
    counts = " ".join(f"{k}={len(v)}" for k, v in items_by_source.items())
    summary = f"[opensource] {counts}"
    print(f"[PHASE:FETCH] {counts}", file=sys.stderr)

    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    period = "72h"

    if dry_run:
        for src, items in items_by_source.items():
            print(f"--- {src} ({len(items)}) ---")
            for it in items[:15]:
                print(f"  • {'[seed] ' if it.get('_seed') else ''}{it.get('title')} "
                      f"⭐{it.get('stars')} | {it.get('url')}")
        print("[OPENSOURCE_DRY_RUN]")
        print(summary)
        return 0

    if no_analyzer:
        try:
            telegram_client.send_digest(items_by_source, bot_token, chat_id)
        except Exception as exc:
            print(f"[opensource] telegram send failed: {exc}", file=sys.stderr)
            return 1
        print("[OPENSOURCE_FALLBACK] --no-analyzer requested")
        print(summary)
        return 0

    prev_state = state.load_state(path=config.STATE_PATH)
    items_with_deltas = state.compute_deltas(items_by_source, prev_state)

    recommended_db = skill_db.load_recommended(path=config.RECOMMENDED_PATH)
    watchlist_db = skill_db.load_watchlist(path=config.WATCHLIST_PATH)

    pre = len(items_with_deltas)
    items_with_deltas = [
        i for i in items_with_deltas
        if not skill_db.is_recommended(recommended_db, i.get("url") or "")
    ]
    dropped = pre - len(items_with_deltas)
    if dropped:
        print(f"[opensource] dropped {dropped} already-recommended repo(s)", file=sys.stderr)

    normalized, annotated = normalizer.normalize(items_by_source)
    cross_map = _build_cross_source_map(annotated)
    items_with_deltas = _annotate_cross_source(items_with_deltas, cross_map)

    expired = skill_db.prune_expired(watchlist_db, date)
    if expired:
        print(f"[opensource] pruned {len(expired)} expired watchlist item(s)", file=sys.stderr)
    graduates = skill_db.check_watchlist_graduates(watchlist_db, items_with_deltas)
    graduate_urls = {g.get("url") for g in graduates if g.get("url")}
    for g in graduates:
        g["graduated_from_watch"] = True

    pre_worth = len(items_with_deltas)
    filtered_items = [it for it in items_with_deltas if _is_worth_showing(it)]
    print(f"[PHASE:FILTER] after_is_recommended={pre_worth} "
          f"after_is_worth_showing={len(filtered_items)} graduates={len(graduates)}",
          file=sys.stderr)

    if not filtered_items and not graduates:
        msg = (f"🧩 Open Source Radar — {date}\n\n"
               "Нет новых open-source решений за период.\n\n"
               f"📊 Источников проверено: {', '.join(items_by_source.keys())}")
        try:
            telegram_client.send_text(msg, bot_token, chat_id)
        except Exception as exc:
            print(f"[opensource] telegram send_text failed: {exc}", file=sys.stderr)
            return 1
        for fn, arg, label in (
            (state.save_state, items_by_source, "state"),
            (skill_db.save_watchlist, watchlist_db, "watchlist"),
        ):
            try:
                fn(arg, path=config.STATE_PATH if label == "state" else config.WATCHLIST_PATH)
            except Exception as exc:
                print(f"[opensource] {label} save failed: {exc}", file=sys.stderr)
        try:
            state.mark_sent_today(path=config.STATE_PATH)
        except Exception as exc:
            print(f"[opensource] mark_sent failed: {exc}", file=sys.stderr)
        print("[OPENSOURCE_NO_NEW_ITEMS]")
        print(summary)
        return 0

    try:
        analysis = analyzer.analyze(
            normalized, filtered_items, period=period, date=date,
            graduated_candidates=graduates, system_prompt=OSS_SYSTEM_PROMPT,
        )
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        print(f"[opensource] analyzer failed: {msg}; fallback to links", file=sys.stderr)
        try:
            telegram_client.send_digest(items_by_source, bot_token, chat_id)
            telegram_client.send_text(
                f"⚠️ Open Source LLM-анализ упал, отправлены плоские ссылки.\nПричина: {msg[:300]}",
                bot_token, chat_id)
        except Exception as exc2:
            print(f"[opensource] telegram fallback failed: {exc2}", file=sys.stderr)
            return 1
        print("[OPENSOURCE_FALLBACK] LLM analysis failed, sent link list.")
        print(summary)
        return 0

    analysis.setdefault("graduated_from_watch", graduates)

    # Owner's seeds are curated picks — guarantee they land in the catalog
    # (recommended), not watch; and backfill real star counts onto promotions.
    _force_promote_seeds(analysis, filtered_items)
    _backfill_promo_meta(analysis, filtered_items)

    telegram_text = analysis.get("telegram_summary") or ""
    if not telegram_text.strip():
        print("[OPENSOURCE_FALLBACK] empty telegram_summary", file=sys.stderr)
        try:
            telegram_client.send_digest(items_by_source, bot_token, chat_id)
        except Exception as exc:
            print(f"[opensource] telegram fallback failed: {exc}", file=sys.stderr)
            return 1
        print("[OPENSOURCE_FALLBACK] empty summary, sent link list.")
        print(summary)
        return 0

    baseline_map = _baseline_metrics(items_with_deltas)
    top_test_items = analysis.get("top_test") or []
    top_watch_items = analysis.get("top_watch") or []

    try:
        added_rec = skill_db.add_to_recommended(recommended_db, top_test_items, date)
        if added_rec:
            print(f"[opensource] added {len(added_rec)} repo(s) to recommended.json", file=sys.stderr)
        promoted_urls = {(it.get("url") or "") for it in top_test_items if isinstance(it, dict)}
        to_remove = (graduate_urls & promoted_urls) | {
            u for u in graduate_urls if u in recommended_db.get("skills", {})
        }
        if to_remove:
            skill_db.remove_from_watchlist(watchlist_db, list(to_remove))
        added_watch = skill_db.add_to_watchlist(
            watchlist_db, top_watch_items, date, baseline_map,
            default_category=config.DEFAULT_CATEGORY,
        )
        if added_watch:
            print(f"[opensource] added {len(added_watch)} repo(s) to watchlist.json", file=sys.stderr)
        skill_db.save_recommended(recommended_db, path=config.RECOMMENDED_PATH)
        skill_db.save_watchlist(watchlist_db, path=config.WATCHLIST_PATH)
    except Exception as exc:
        print(f"[opensource] skill_db save failed: {exc}", file=sys.stderr)

    try:
        index_writer.write_indexes(
            recommended_db, base_dir=config.INDEX_DIR,
            categories=config.CATEGORIES, default_category=config.DEFAULT_CATEGORY,
        )
    except Exception as exc:
        print(f"[opensource] index write failed: {exc}", file=sys.stderr)

    try:
        report_path = _write_report(analysis, date)
        print(f"[opensource] wrote {report_path}")
        try:
            state.save_state(items_by_source, path=config.STATE_PATH)
        except Exception as exc:
            print(f"[opensource] state save failed: {exc}", file=sys.stderr)
    except Exception as exc:
        print(f"[opensource] report write failed: {exc}", file=sys.stderr)

    try:
        telegram_client.send_text(telegram_text, bot_token, chat_id)
    except Exception as exc:
        print(f"[opensource] telegram send_text failed: {exc}", file=sys.stderr)
        return 1

    try:
        state.mark_sent_today(path=config.STATE_PATH)
    except Exception as exc:
        print(f"[opensource] mark_sent failed: {exc}", file=sys.stderr)

    print("[OPENSOURCE_ANALYSIS_OK]")
    print(summary)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Open Source radar digest")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print fetched repos instead of sending (no API calls)")
    parser.add_argument("--no-analyzer", action="store_true",
                        help="Skip LLM analysis; send the legacy link digest")
    parser.add_argument("--force", action="store_true",
                        help="Bypass the once-per-day idempotency guard")
    args = parser.parse_args()
    return run(dry_run=args.dry_run, no_analyzer=args.no_analyzer, force=args.force)


if __name__ == "__main__":
    sys.exit(main())
