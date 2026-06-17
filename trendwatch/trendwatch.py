#!/usr/bin/env python3
"""Trendwatch orchestrator: fetch -> normalize+deltas -> LLM analyze -> Telegram.

The LLM step (analyzer) is the new heart of the pipeline; on failure we fall
back to the original "list of links" digest so the user still gets something
in Telegram.

Sprint 5 adds a persistent skill database:
- ``digests/recommended.json`` — repos that have already been promoted to
  ``top_test`` once. Excluded from future digests (no double recommendations).
- ``digests/watchlist.json`` — repos the model wanted to watch with their
  ``signal_to_wait``; on each run we check whether real metrics met the signal
  and graduate the item back into the analyzer as a priority candidate.
- ``digests/index/`` — browsable Markdown indexes regenerated from
  recommended.json on every successful run. Public links to these indexes are
  appended to the Telegram digest.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

try:
    from . import config
    from .sources.github import fetch_github
    from .sources.reddit import fetch_reddit
    from .sources.twitter import fetch_twitter
    from .sources.threads import fetch_threads
    from . import telegram_client

    from . import analyzer
    from . import catalog
    from . import enrich
    from . import import_payload
    from . import index_writer
    from . import normalizer
    from . import report
    from . import skill_db
    from . import state
except ImportError:
    import config
    from sources.github import fetch_github
    from sources.reddit import fetch_reddit
    from sources.twitter import fetch_twitter
    from sources.threads import fetch_threads
    import telegram_client

    import analyzer
    import catalog
    import enrich
    import import_payload
    import index_writer
    import normalizer
    import report
    import skill_db
    import state


def _api_key_fingerprint() -> str:
    """Return a safe, human-comparable fingerprint of the API key in env so
    the user can match it against the key shown in Anthropic console without
    the actual secret ever reaching Telegram.
    """
    raw = os.environ.get("ANTHROPIC_API_KEY", "")
    stripped = raw.strip()
    if not stripped:
        return "<empty>"
    # Anthropic console shows the last 4 chars of each key. Match that
    # format. Also surface len + whether there was whitespace polluting
    # the env var — the most common cause of 401 here.
    pollution = " (had whitespace)" if raw != stripped else ""
    return f"len={len(stripped)} ...{stripped[-4:]}{pollution}"


def _fallback_with_reason(
    exc: Exception, items_by_source, bot_token: str, chat_id: str, summary: str
) -> int:
    """Send the plain-link fallback, then a short error-cause note so the
    failure is visible in Telegram (not buried in Actions stderr).
    Returns the exit code the orchestrator should use.
    """
    msg = f"{type(exc).__name__}: {exc}"
    print(
        f"[trendwatch] analyzer failed: {msg}; falling back to link digest",
        file=sys.stderr,
    )
    try:
        telegram_client.send_digest(items_by_source, bot_token, chat_id)
    except Exception as exc2:
        print(f"[trendwatch] telegram fallback failed: {exc2}", file=sys.stderr)
        print(summary)
        return 1
    note = (
        f"⚠️ LLM-анализ упал, отправлены плоские ссылки.\n"
        f"Причина: {msg[:300]}\n"
        f"Ключ: {_api_key_fingerprint()}"
    )
    try:
        telegram_client.send_text(note, bot_token, chat_id)
    except Exception as exc2:
        print(f"[trendwatch] reason-note send failed: {exc2}", file=sys.stderr)
    print("[FALLBACK_LINKS] LLM analysis failed, sent link list.")
    print(summary)
    return 0


def _is_worth_showing(item: dict) -> bool:
    """Dedupe filter: include items only if new, gained skills, grew ≥5 stars,
    or absolute stars ≥500 (high-star repos always get re-evaluated by the
    LLM even without delta — otherwise a 7k-star repo seen once with zero
    daily growth would silently never reach the analyzer again).
    """
    if item.get("is_new", True):
        return True
    if item.get("has_new_skills"):
        return True
    delta = item.get("delta_stars") or 0
    if isinstance(delta, int) and delta >= 5:
        return True
    stars = item.get("stars") or 0
    if isinstance(stars, int) and stars >= 100:
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


def _write_report(analysis: dict, date: str, items: list[dict] | None = None) -> str:
    os.makedirs("digests", exist_ok=True)
    path = os.path.join("digests", f"{date}.md")
    md = report.to_markdown(analysis, date, items=items)
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    return path


def _build_cross_source_map(annotated_items: list[dict]) -> dict[str, int]:
    """For each URL, return how many distinct sources mentioned it.

    Reuses ``matched_names`` produced by ``normalizer.normalize``: an item's
    cross_source_count is the max, across all of its matched_names, of the
    number of sources where that name has at least one mention. Falls back to 1
    if the item has no matched names.
    """
    # source counts per name
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
        # keep the max across duplicate URLs across sources
        out[url] = max(out.get(url, 0), best)
    return out


def _annotate_cross_source(
    items_with_deltas: list[dict], cross_map: dict[str, int]
) -> list[dict]:
    for it in items_with_deltas or []:
        url = it.get("url")
        if url and url in cross_map:
            it["cross_source_count"] = cross_map[url]
    return items_with_deltas


def _baseline_metrics(items_with_deltas: list[dict]) -> dict[str, dict]:
    """Build URL → {stars, skills_count, cross_source_count} for watchlist baseline."""
    out: dict[str, dict] = {}
    for it in items_with_deltas or []:
        url = it.get("url") or ""
        if not url:
            continue
        out[url] = {
            "stars": it.get("stars"),
            "skills_count": it.get("skills_count"),
            "cross_source_count": it.get("cross_source_count"),
        }
    return out


def run(
    dry_run: bool = False, no_analyzer: bool = False, force: bool = False
) -> int:
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

    # Idempotency guard: skip if a digest was already sent today. Protects
    # the Anthropic API budget against manual workflow_dispatch retries.
    if not dry_run and not force and state.was_sent_today():
        print("[ALREADY_SENT_TODAY] skills digest already sent today, skipping")
        return 0

    items_by_source = _fetch_all()
    counts = " ".join(f"{k}={len(v)}" for k, v in items_by_source.items())
    summary = f"[trendwatch] {counts}"
    print(f"[PHASE:FETCH] {counts}", file=sys.stderr)

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

    # Persistent skill DB load
    recommended_db = skill_db.load_recommended()
    watchlist_db = skill_db.load_watchlist()

    # Filter out repos already permanently recommended.
    pre_filter_count = len(items_with_deltas)
    items_with_deltas = [
        i for i in items_with_deltas
        if not skill_db.is_recommended(recommended_db, i.get("url") or "")
    ]
    dropped_recommended = pre_filter_count - len(items_with_deltas)
    if dropped_recommended:
        print(
            f"[trendwatch] dropped {dropped_recommended} already-recommended repo(s)",
            file=sys.stderr,
        )

    normalized, annotated = normalizer.normalize(items_by_source)
    cross_map = _build_cross_source_map(annotated)
    items_with_deltas = _annotate_cross_source(items_with_deltas, cross_map)

    # Watchlist maintenance: prune expired, then check graduates.
    expired = skill_db.prune_expired(watchlist_db, date)
    if expired:
        print(
            f"[trendwatch] pruned {len(expired)} expired watchlist item(s)",
            file=sys.stderr,
        )
    graduates = skill_db.check_watchlist_graduates(watchlist_db, items_with_deltas)
    graduate_urls = {g.get("url") for g in graduates if g.get("url")}
    for g in graduates:
        g["graduated_from_watch"] = True
        # trigger already set by check_watchlist_graduates

    # Dedupe filter: drop items that were already shown without material change.
    pre_worth_count = len(items_with_deltas)
    filtered_items = [it for it in items_with_deltas if _is_worth_showing(it)]
    print(
        f"[PHASE:FILTER] after_is_recommended={pre_worth_count} "
        f"after_is_worth_showing={len(filtered_items)} "
        f"graduates={len(graduates)}",
        file=sys.stderr,
    )

    if not filtered_items and not graduates:
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
        # Save state + watchlist (last_checked / prune updates) so we don't
        # re-find the same items next run.
        try:
            state.save_state(items_by_source)
        except Exception as exc:
            print(f"[trendwatch] state save failed: {exc}", file=sys.stderr)
        try:
            skill_db.save_watchlist(watchlist_db)
        except Exception as exc:
            print(f"[trendwatch] watchlist save failed: {exc}", file=sys.stderr)
        try:
            state.mark_sent_today()
        except Exception as exc:
            print(f"[trendwatch] mark_sent failed: {exc}", file=sys.stderr)
        print("[NO_NEW_ITEMS]")
        print(summary)
        return 0

    try:
        analysis = analyzer.analyze(
            normalized,
            filtered_items,
            period=period,
            date=date,
            graduated_candidates=graduates,
        )
    except TypeError:
        # Backwards-compat: older analyzer signature without graduated_candidates.
        try:
            analysis = analyzer.analyze(
                normalized, filtered_items, period=period, date=date
            )
        except Exception as exc:
            return _fallback_with_reason(
                exc, items_by_source, bot_token, chat_id, summary
            )
    except Exception as exc:
        return _fallback_with_reason(
            exc, items_by_source, bot_token, chat_id, summary
        )

    # Surface graduates in the rendered Markdown report too.
    analysis.setdefault("graduated_from_watch", graduates)

    # Check telegram_summary BEFORE any persistence — empty means the analyzer
    # effectively failed, so treat as fallback and do NOT mutate state/DB.
    telegram_text = analysis.get("telegram_summary") or ""
    if not telegram_text.strip():
        print(
            "[FALLBACK_LINKS] empty telegram_summary from analyzer",
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

    # Persist DB changes (only on full analyzer success with non-empty summary).
    baseline_map = _baseline_metrics(items_with_deltas)
    top_test_items = analysis.get("top_test") or []
    top_watch_items = analysis.get("top_watch") or []

    try:
        added_rec = skill_db.add_to_recommended(
            recommended_db, top_test_items, date
        )
        if added_rec:
            print(
                f"[trendwatch] added {len(added_rec)} repo(s) to recommended.json",
                file=sys.stderr,
            )
        # Anything that graduated AND ended up in top_test should be removed
        # from the watchlist; also drop any graduate explicitly listed even if
        # the model placed it elsewhere (avoid stuck items).
        promoted_urls = {
            (it.get("url") or "")
            for it in top_test_items
            if isinstance(it, dict)
        }
        to_remove = (graduate_urls & promoted_urls) | {
            u for u in graduate_urls if u in recommended_db.get("skills", {})
        }
        if to_remove:
            skill_db.remove_from_watchlist(watchlist_db, list(to_remove))

        added_watch = skill_db.add_to_watchlist(
            watchlist_db, top_watch_items, date, baseline_map
        )
        if added_watch:
            print(
                f"[trendwatch] added {len(added_watch)} repo(s) to watchlist.json",
                file=sys.stderr,
            )
        skill_db.save_recommended(recommended_db)
        skill_db.save_watchlist(watchlist_db)
    except Exception as exc:
        print(f"[trendwatch] skill_db save failed: {exc}", file=sys.stderr)

    # Regenerate Markdown indexes from the up-to-date recommended DB.
    try:
        index_writer.write_indexes(recommended_db)
    except Exception as exc:
        print(f"[trendwatch] index write failed: {exc}", file=sys.stderr)

    # Build the catalog Import payload, enrich each test_now skill via Claude
    # (reads SKILL.md), then embed the SAME enriched payload in the report and
    # push it to the web catalog. Each step degrades gracefully on failure.
    payload = None
    try:
        payload = import_payload.build_payload(analysis, items_with_deltas, date)
        try:
            extra_suggested = enrich.enrich_payload(payload)
            import_payload.apply_category_updates(payload, extra_suggested)
        except Exception as exc:
            print(f"[trendwatch] skill enrichment failed: {exc}", file=sys.stderr)
    except Exception as exc:
        print(f"[trendwatch] payload build failed: {exc}", file=sys.stderr)

    try:
        report_path = _write_report(analysis, date, payload=payload)
        print(f"[trendwatch] wrote {report_path}")
        try:
            state.save_state(items_by_source)
        except Exception as exc:
            print(f"[trendwatch] state save failed: {exc}", file=sys.stderr)
    except Exception as exc:
        print(f"[trendwatch] report write failed: {exc}", file=sys.stderr)

    try:
        telegram_client.send_text(telegram_text, bot_token, chat_id)
    except Exception as exc:
        print(f"[trendwatch] telegram send_text failed: {exc}", file=sys.stderr)
        print(summary)
        return 1

    if payload is not None:
        _push_to_catalog(payload, bot_token, chat_id)

    try:
        state.mark_sent_today()
    except Exception as exc:
        print(f"[trendwatch] mark_sent failed: {exc}", file=sys.stderr)

    print("[ANALYSIS_OK]")
    print(summary)
    return 0


def _push_to_catalog(payload: dict, bot_token: str = "", chat_id: str = "") -> None:
    """One idempotent POST of the Import payload to the web catalog. Logs the
    response counts and surfaces any suggested categories to the owner via
    Telegram. Never raises."""
    result, error = catalog.push_payload(payload)
    if error:
        print(f"[trendwatch] catalog push skipped/failed: {error}", file=sys.stderr)
        return
    print(f"[trendwatch] catalog push OK: {catalog.format_summary(result)}")
    print(f"[trendwatch] ingest response: {json.dumps(result, ensure_ascii=False)}")
    _notify_suggested(catalog.suggested_categories(result), bot_token, chat_id)


def _notify_suggested(suggested: list[dict], bot_token: str, chat_id: str) -> None:
    """Surface catalog-proposed new categories to the owner via Telegram."""
    if not suggested or not bot_token or not chat_id:
        return
    lines = ["🆕 Предложены новые категории каталога (нужно решение):"]
    for s in suggested:
        slug = s.get("slug", "?")
        name = s.get("name", "")
        rationale = s.get("rationale", "")
        line = f"• {slug}" + (f" — {name}" if name else "")
        if rationale:
            line += f": {rationale}"
        lines.append(line)
    try:
        telegram_client.send_text("\n".join(lines), bot_token, chat_id)
    except Exception as exc:
        print(f"[trendwatch] suggested-categories notify failed: {exc}", file=sys.stderr)


def _parse_owner_repo(url: str) -> str | None:
    m = import_payload._GITHUB_RE.search(url or "")
    if not m:
        return None
    repo = m.group(2)
    if repo.endswith(".git"):
        repo = repo[:-4]
    return f"{m.group(1)}/{repo}"


def run_backfill(urls: list[str]) -> int:
    """One-off catch-up: take repo URLs, enrich every skill, push to catalog.

    No analyzer / Telegram digest — just list each repo's ``.claude/skills``
    folders, build the payload, enrich via Claude, and POST it.
    """
    try:
        from .sources import github as gh_source
    except ImportError:  # pragma: no cover
        from sources import github as gh_source

    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    repos: list[dict] = []
    for url in urls:
        owner_repo = _parse_owner_repo(url)
        if not owner_repo:
            print(f"[backfill] not a GitHub repo URL, skipping: {url}", file=sys.stderr)
            continue
        meta = gh_source._repo_meta(owner_repo)
        branch = meta.get("default_branch") or "main"
        dirs = gh_source._list_skill_dirs(owner_repo)
        if dirs == gh_source.RATE_LIMITED:
            print(f"[backfill] rate-limited listing {owner_repo}, skipping", file=sys.stderr)
            continue
        if not dirs:
            print(f"[backfill] no .claude/skills in {owner_repo}, skipping", file=sys.stderr)
            continue
        repos.append(
            import_payload.make_repo_entry(
                owner_repo, branch, dirs,
                stars=meta.get("stars"), category="general",
            )
        )
        print(f"[backfill] {owner_repo}: {len(dirs)} skill(s)", file=sys.stderr)

    if not repos:
        print("[backfill] nothing to push")
        return 0

    payload = import_payload.assemble_payload(repos, date)
    try:
        extra = enrich.enrich_payload(payload)
        import_payload.apply_category_updates(payload, extra)
    except Exception as exc:
        print(f"[backfill] enrichment failed: {exc}", file=sys.stderr)

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    result, error = catalog.push_payload(payload)
    if error:
        print(f"[backfill] catalog push failed: {error}", file=sys.stderr)
        return 1
    print(f"[backfill] catalog push OK: {catalog.format_summary(result)}")
    print(f"[backfill] ingest response: {json.dumps(result, ensure_ascii=False)}")
    _notify_suggested(catalog.suggested_categories(result), bot_token, chat_id)
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
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass the once-per-day idempotency guard (for manual reruns).",
    )
    parser.add_argument(
        "--backfill",
        nargs="*",
        metavar="REPO_URL",
        help="Backfill mode: enrich + push these GitHub repo URLs to the catalog "
        "(no analyzer/Telegram). Combine with --backfill-file.",
    )
    parser.add_argument(
        "--backfill-file",
        metavar="PATH",
        help="Backfill mode: read repo URLs (one per line) from this file.",
    )
    args = parser.parse_args()

    if args.backfill is not None or args.backfill_file:
        urls: list[str] = list(args.backfill or [])
        if args.backfill_file:
            with open(args.backfill_file, encoding="utf-8") as f:
                urls += [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
        if not urls:
            print("[backfill] no URLs provided", file=sys.stderr)
            return 1
        return run_backfill(urls)

    return run(
        dry_run=args.dry_run, no_analyzer=args.no_analyzer, force=args.force
    )


if __name__ == "__main__":
    sys.exit(main())
